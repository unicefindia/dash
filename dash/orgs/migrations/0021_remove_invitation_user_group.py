# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0020_populate_invitation_group'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='invitation',
            name='user_group',
        ),
    ]
