import logging
import time

from django_redis import get_redis_connection
from djcelery.app import app

from .models import Invitation, Org


logger = logging.getLogger(__name__)


@app.task(track_started=True, name='send_invitation_email_task')
def send_invitation_email_task(invitation_id):
    invitation = Invitation.objects.get(pk=invitation_id)
    invitation.send_email()


@app.task(name='orgs.build_boundaries')
def build_boundaries():
    start = time.time()
    r = get_redis_connection()

    key = 'build_boundaries'
    if not r.get(key):
        with r.lock(key, timeout=900):
            active_orgs = Org.objects.filter(is_active=True)
            for org in active_orgs:
                logger.debug("=" * 40)
                org.build_boundaries()
    logger.debug("Task: build_boundaries took %ss" % (time.time() - start))
