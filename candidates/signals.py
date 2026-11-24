from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Role

from .models import CandidateProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="create_candidate_profile")
def create_candidate_profile(sender, instance, update_fields=None, **kwargs):
    """Give every candidate a CandidateProfile, however the user was saved.

    Saves that only touch other fields (e.g. last_login at each login) are
    skipped, so logging in costs no extra query.
    """
    if update_fields is not None and "role" not in update_fields:
        return
    if instance.role == Role.CANDIDATE:
        CandidateProfile.objects.get_or_create(user=instance)
