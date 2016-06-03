# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def populate_user_roles(apps, schema_editor):
    Org = apps.get_model('orgs', 'Org')
    UserRole = apps.get_model('orgs', 'UserRole')
    Group = apps.get_model('auth', 'Group')

    def get_or_create_group(name):
        group = Group.objects.filter(name=name).first()
        if not group:
            group = Group.objects.create(name=name)
        return group

    admins = get_or_create_group("Administrators")
    editors = get_or_create_group("Editors")
    viewers = get_or_create_group("Viewers")

    for org in Org.objects.all():
        for user in org.administrators.all():
            UserRole.objects.create(org, user, admins)
        for user in org.editors.all():
            UserRole.objects.create(org, user, editors)
        for user in org.viewers.all():
            UserRole.objects.create(org, user, viewers)


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0017_user_role'),
    ]

    operations = [
        migrations.RunPython(populate_user_roles)
    ]
