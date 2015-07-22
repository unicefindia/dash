from __future__ import unicode_literals

from timezones.forms import TimeZoneField

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

from .models import Org


class OrgForm(forms.ModelForm):
    first_name = forms.CharField(help_text=_("Your first name"))
    last_name = forms.CharField(help_text=_("Your last name"))
    email = forms.EmailField(help_text=_("Your email address"))
    password = forms.CharField(widget=forms.PasswordInput,
                               help_text=_("Your password, at least eight letters please"))

    timezone = TimeZoneField()

    def __init__(self, *args, **kwargs):
        super(OrgForm, self).__init__(*args, **kwargs)
        administrators = User.objects.exclude(username__in=['root', 'root2'])
        administrators = administrators.exclude(pk__lt=0)
        self.fields['administrators'].queryset = administrators
        self.fields['language'].choices = settings.LANGUAGES

    def clean_email(self):
        email = self.cleaned_data['email']
        if email:
            if User.objects.filter(username__iexact=email):
                raise forms.ValidationError(_("That email address is already used"))

        return email.lower()

    def clean_password(self):
        password = self.cleaned_data['password']
        if password:
            if not len(password) >= 8:
                raise forms.ValidationError(_("Passwords must contain at least 8 letters."))
        return password

    def clean_domain(self):
        domain = self.cleaned_data['domain']
        domain = domain.strip().lower()
        if not domain:
            return None

        if domain and domain == getattr(settings, 'HOSTNAME', ""):
            raise forms.ValidationError(_("This domain is used for subdomains"))
        return domain

    class Meta:
        fields = ('is_active', 'first_name', 'last_name', 'email', 'password',
                  'name', 'subdomain', 'domain', 'timezone', 'language',
                  'api_token', 'logo', 'administrators')
        model = Org
