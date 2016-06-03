from __future__ import unicode_literals

import json
import random
import pytz

from dash.dash_email import send_dash_email
from dash.utils import datetime_to_ms, get_obj_cacheable
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_text, python_2_unicode_compatible
from smartmin.models import SmartModel
from temba_client.v1 import TembaClient as TembaClient1
from temba_client.v2 import TembaClient as TembaClient2

# groups used for different org roles
DEFAULT_ORG_GROUPS = ('Administrators', 'Editors', 'Viewers')

STATE = 1
DISTRICT = 2

# we cache boundary data for a month at a time
BOUNDARY_CACHE_TIME = getattr(settings, 'API_BOUNDARY_CACHE_TIME', 60 * 60 * 24 * 30)

BOUNDARY_CACHE_KEY = 'org:%d:boundaries'
BOUNDARY_LEVEL_1_KEY = 'geojson:%d'
BOUNDARY_LEVEL_2_KEY = 'geojson:%d:%s'


@python_2_unicode_compatible
class Org(SmartModel):
    name = models.CharField(
        verbose_name=_("Name"), max_length=128,
        help_text=_("The name of this organization"))

    logo = models.ImageField(
        upload_to='logos', null=True, blank=True,
        help_text=_("The logo that should be used for this organization"))

    language = models.CharField(
        verbose_name=_("Language"), max_length=64, null=True, blank=True,
        help_text=_("The main language used by this organization"))

    subdomain = models.SlugField(
        verbose_name=_("Subdomain"), null=True, blank=True, max_length=255, unique=True,
        error_messages=dict(unique=_("This subdomain is not available")),
        help_text=_("The subdomain for this organization"))

    domain = models.CharField(
        verbose_name=_("Domain"), null=True, blank=True, max_length=255, unique=True,
        error_messages=dict(unique=_("This domain is not available")),
        help_text=_("The custom domain for this organization"))

    timezone = models.CharField(
        verbose_name=_("Timezone"), max_length=64, default='UTC',
        help_text=_("The timezone your organization is in."))

    api_token = models.CharField(
        max_length=128, null=True, blank=True,
        help_text=_("The API token for the RapidPro account this dashboard "
                    "is tied to"))

    config = models.TextField(
        null=True, blank=True,
        help_text=_("JSON blob used to store configuration information "
                    "associated with this organization"))

    def set_timezone(self, timezone):
        self.timezone = timezone
        self._tzinfo = None

    def get_timezone(self):
        tzinfo = getattr(self, '_tzinfo', None)

        if not tzinfo:
            # we need to build the pytz timezone object with a context of now
            tzinfo = timezone.now().astimezone(pytz.timezone(self.timezone)).tzinfo
            self._tzinfo = tzinfo

        return tzinfo

    def get_config(self, name, default=None):
        config = getattr(self, '_config', None)

        if config is None:
            if not self.config:
                return default

            config = json.loads(self.config)
            self._config = config

        return config.get(name, default)

    def set_config(self, name, value, commit=True):
        if not self.config:
            config = dict()
        else:
            config = json.loads(self.config)

        config[name] = value
        self.config = json.dumps(config)
        self._config = config

        if commit:
            self.save()

    def get_org_admins(self):
        return User.objects.filter(org_roles__org=self, org_roles__group=Group.objects.get(name='Administrators'))

    def get_org_editors(self):
        return User.objects.filter(org_roles__org=self, org_roles__group=Group.objects.get(name='Editors'))

    def get_org_viewers(self):
        return User.objects.filter(org_roles__org=self, org_roles__group=Group.objects.get(name='Viewers'))

    def get_org_users(self):
        return User.objects.filter(org_roles__org=self).distinct()

    def get_user_org_group(self, user):
        """
        Users can have multiple roles in an org - this returns the first role using order of ORG_GROUPS
        """
        return get_obj_cacheable(user, '_org_group', lambda: self._get_user_org_group(user))

    def _get_user_org_group(self, user):
        user_groups_by_name = {group.name: group for group in UserRole.get_org_groups(self, user)}

        for group_name in getattr(settings, 'ORG_GROUPS', DEFAULT_ORG_GROUPS):
            if group_name in user_groups_by_name.keys():
                return user_groups_by_name[group_name]

        return None

    def grant_role(self, user, group_name):
        UserRole.grant(self, user, group_name)

    def revoke_role(self, user, group_name):
        UserRole.revoke(self, user, group_name)

    def get_temba_client(self, api_version=1):
        if api_version not in (1, 2):
            raise ValueError("Unsupported RapidPro API version: %d" % api_version)

        host = getattr(settings, 'SITE_API_HOST', None)
        agent = getattr(settings, 'SITE_API_USER_AGENT', None)

        if host.endswith('api/v1') or host.endswith('api/v1/'):
            raise ValueError("API host should not include API version, "
                             "e.g. http://example.com instead of http://example.com/api/v1")

        client_cls = TembaClient1 if api_version == 1 else TembaClient2

        return client_cls(host, self.api_token, user_agent=agent)

    def build_host_link(self, user_authenticated=False):
        host_tld = getattr(settings, "HOSTNAME", 'locahost')
        is_secure = getattr(settings, 'SESSION_COOKIE_SECURE', False)

        prefix = 'http://'

        if self.domain and is_secure and not user_authenticated:
            return prefix + str(self.domain)

        if is_secure:
            prefix = 'https://'

        if self.subdomain == '':
            return prefix + host_tld
        return prefix + force_text(self.subdomain) + "." + host_tld

    @classmethod
    def rebuild_org_boundaries_task(cls, org):
        from dash.orgs.tasks import rebuild_org_boundaries
        rebuild_org_boundaries.delay(org.pk)

    def build_boundaries(self):

        this_time = datetime.now()
        temba_client = self.get_temba_client()
        client_boundaries = temba_client.get_boundaries()

        # we now build our cached versions of level 1 (all states) and level 2
        # (all districts for each state) geojson
        states = []
        districts_by_state = dict()
        for boundary in client_boundaries:
            if boundary.level == STATE:
                states.append(boundary)
            elif boundary.level == DISTRICT:
                osm_id = boundary.parent
                if osm_id not in districts_by_state:
                    districts_by_state[osm_id] = []

                districts = districts_by_state[osm_id]
                districts.append(boundary)

        # mini function to convert a list of boundary objects to geojson
        def to_geojson(boundary_list):
            features = [dict(type='Feature',
                             geometry=dict(type=b.geometry.type,
                                           coordinates=b.geometry.coordinates),
                             properties=dict(name=b.name, id=b.boundary, level=b.level))
                        for b in boundary_list]
            return dict(type='FeatureCollection', features=features)

        boundaries = dict()
        boundaries[BOUNDARY_LEVEL_1_KEY % self.id] = to_geojson(states)

        for state_id in districts_by_state.keys():
            boundaries[BOUNDARY_LEVEL_2_KEY % (self.id, state_id)] = to_geojson(
                districts_by_state[state_id])

        key = BOUNDARY_CACHE_KEY % self.pk
        value = {'time': datetime_to_ms(this_time), 'results': boundaries}
        cache.set(key, value, BOUNDARY_CACHE_TIME)

        return boundaries

    def get_boundaries(self):
        key = BOUNDARY_CACHE_KEY % self.pk
        cached_value = cache.get(key, None)
        if cached_value:
            return cached_value['results']
        Org.rebuild_org_boundaries_task(self)

    def get_country_geojson(self):
        boundaries = self.get_boundaries()
        if boundaries:
            key = BOUNDARY_LEVEL_1_KEY % self.id
            return boundaries.get(key, None)

    def get_state_geojson(self, state_id):
        boundaries = self.get_boundaries()
        if boundaries:
            key = BOUNDARY_LEVEL_2_KEY % (self.id, state_id)
            return boundaries.get(key, None)

    def get_top_level_geojson_ids(self):
        org_country_boundaries = self.get_country_geojson()
        return [elt['properties']['id'] for elt in org_country_boundaries['features']]

    def get_task_state(self, task_key):
        return TaskState.get_or_create(self, task_key)

    def __str__(self):
        return self.name


class UserRole(models.Model):
    org = models.ForeignKey(Org, related_name='user_roles')

    user = models.ForeignKey(User, related_name='org_roles')

    group = models.ForeignKey(Group, related_name='org_roles')

    @classmethod
    def grant(cls, org, user, group_name):
        if not cls.objects.filter(org=org, user=user, group__name=group_name):
            cls.objects.create(org=org, user=user, group=Group.objects.get(name=group_name))

    @classmethod
    def revoke(cls, org, user, group_name):
        cls.objects.filter(org=org, user=user, group__name=group_name).delete()

    @classmethod
    def get_org_groups(cls, org, user):
        return Group.objects.filter(org_roles__org=org, org_roles__user=user)

    class Meta:
        unique_together = ('org', 'user', 'group')


class Invitation(SmartModel):
    org = models.ForeignKey(
        Org, verbose_name=_("Org"), related_name="invitations",
        help_text=_("The organization to which the account is invited to view"))

    email = models.EmailField(
        verbose_name=_("Email"),
        help_text=_("The email to which we send the invitation of the viewer"))

    secret = models.CharField(
        verbose_name=_("Secret"), max_length=64, unique=True,
        help_text=_("a unique code associated with this invitation"))

    group = models.ForeignKey(Group, verbose_name=_("User Role"), null=True)

    def save(self, *args, **kwargs):
        if not self.secret:
            secret = Invitation.generate_random_string(64)

            while Invitation.objects.filter(secret=secret):
                secret = Invitation.generate_random_string(64)

            self.secret = secret

        return super(Invitation, self).save(*args, **kwargs)

    @classmethod
    def generate_random_string(cls, length):
        """
        Generatesa a [length] characters alpha numeric secret
        """
        # avoid things that could be mistaken ex: 'I' and '1'
        letters = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        return ''.join([random.choice(letters) for _ in range(length)])

    def send_invitation(self):
        from .tasks import send_invitation_email_task
        send_invitation_email_task(self.id)

    def send_email(self):
        # no=op if we do not know the email
        if not self.email:
            return

        subject = _("%s Invitation") % self.org.name
        template = "orgs/email/invitation_email"
        to_email = self.email

        context = dict(org=self.org, now=timezone.now(), invitation=self)
        context['subject'] = subject
        context['host'] = self.org.build_host_link()

        send_dash_email(to_email, subject, template, context)


class OrgBackground(SmartModel):
    BACKGROUND_TYPES = (('B', _("Banner")),
                        ('P', _("Pattern")))

    org = models.ForeignKey(
        Org, verbose_name=_("Org"), related_name="backgrounds",
        help_text=_("The organization in which the image will be used"))

    name = models.CharField(
        verbose_name=_("Name"), max_length=128,
        help_text=_("The name to describe this background"))

    background_type = models.CharField(
        max_length=1, choices=BACKGROUND_TYPES, default='P', verbose_name=_("Background type"))

    image = models.ImageField(upload_to='org_bgs', help_text=_("The image file"))


class TaskState(models.Model):
    """
    Holds org specific state for a scheduled task
    """
    org = models.ForeignKey(Org, related_name='task_states')

    task_key = models.CharField(max_length=32)

    started_on = models.DateTimeField(null=True)

    ended_on = models.DateTimeField(null=True)

    last_successfully_started_on = models.DateTimeField(null=True)

    last_results = models.TextField(null=True)

    is_failing = models.BooleanField(default=False)

    is_disabled = models.BooleanField(default=False)

    @classmethod
    def get_or_create(cls, org, task_key):
        existing = cls.objects.filter(org=org, task_key=task_key).first()
        if existing:
            return existing

        return cls.objects.create(org=org, task_key=task_key)

    @classmethod
    def get_failing(cls):
        return cls.objects.filter(org__is_active=True, is_failing=True)

    def is_running(self):
        return self.started_on and not self.ended_on

    def has_ever_run(self):
        return self.started_on is not None

    def get_last_results(self):
        return json.loads(self.last_results) if self.last_results else None

    def get_time_taken(self):
        until = self.ended_on if self.ended_on else timezone.now()
        return (until - self.started_on).total_seconds()

    class Meta:
        unique_together = ('org', 'task_key')


# =============================================================================================
# Monkey patching for user model
# =============================================================================================

def _get_org(user):
    return getattr(user, '_org', None)


def _set_org(user, org):
    user._org = org


def _get_user_orgs(user):
    if user.is_superuser:
        return Org.objects.all()

    return Org.objects.filter(user_roles=user, is_active=True).distinct()


def _get_org_group(user, org=None):
    if not org:
        org = user.get_org()

    return org.get_user_org_group(user)


User.get_org = _get_org
User.set_org = _set_org
User.get_user_orgs = _get_user_orgs
User.get_org_group = _get_org_group
