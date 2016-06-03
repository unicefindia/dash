# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0006_require_contenttypes_0002'),
        ('orgs', '0018_populate_user_roles'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='org',
            name='administrators',
        ),
        migrations.RemoveField(
            model_name='org',
            name='editors',
        ),
        migrations.RemoveField(
            model_name='org',
            name='viewers',
        ),
        migrations.AddField(
            model_name='invitation',
            name='group',
            field=models.ForeignKey(verbose_name='User Role', to='auth.Group', null=True),
        ),
        migrations.AlterField(
            model_name='userrole',
            name='user',
            field=models.ForeignKey(related_name='org_roles', to=settings.AUTH_USER_MODEL),
        ),
    ]
