from __future__ import absolute_import, unicode_literals

from django.contrib.auth.models import User

# increase username/email field sizes
field = User._meta.get_field('email')
field.max_length = 254
field = User._meta.get_field('username')
field.max_length = 254
