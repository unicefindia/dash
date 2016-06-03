# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def populate_invitation_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Invitation = apps.get_model('orgs', 'Invitation')

    groups = {
        'A': Group.objects.get(name='Administrators'),
        'E': Group.objects.get(name='Editors'),
        'V': Group.objects.get(name='Viewers'),
    }

    for invitation in Invitation.objects.all():
        group = groups.get(invitation.user_group)
        invitation.group = group
        invitation.save(update_fields=('group',))


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0019_auto_20160603_1430'),
    ]

    operations = [
        migrations.RunPython(populate_invitation_groups)
    ]
