import logging
import sys

from django.db.models import Q
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from ..manager.models import Topography, post_renew_cache
from .models import Analysis

_log = logging.getLogger(__name__)

# Detect whether we are running within a Celery worker. This solution was suggested here:
# https://stackoverflow.com/questions/39003282/how-can-i-detect-whether-im-running-in-a-celery-worker
_IN_CELERY_WORKER_PROCESS = (
    sys.argv and sys.argv[0].endswith("celery") and "worker" in sys.argv
)


@receiver(post_renew_cache, sender=Topography)
def post_renew_measurement_cache(sender, instance, **kwargs):
    # Cache is renewed, this means something significant changed and we need to remove
    # the analyses
    _log.debug(
        f"Cache of measurement {instance} was renewed: Deleting all affected "
        "analyses..."
    )
    Analysis.objects.filter(
        Q(subject_dispatch__topography=instance) | Q(subject_dispatch__surface=instance.surface)
    ).delete()


@receiver(pre_save, sender=Topography)
def pre_measurement_save(sender, instance, **kwargs):
    created = instance.pk is None
    if created:
        # Measurement was created and added to a dataset: We need to delete the
        # corresponding dataset analysis
        _log.debug(
            f"A measurement was added to dataset {instance.surface}: Deleting all "
            "affected analyses..."
        )
        Analysis.objects.filter(subject_dispatch__surface=instance.surface).delete()


@receiver(post_delete, sender=Topography)
def post_measurement_delete(sender, instance, **kwargs):
    # The topography analysis is automatically deleted, but we have to delete the
    # corresponding surface analysis; we do this after the transaction has finished
    # so we can check whether the surface still exists.
    _log.debug(
        f"Measurement {instance} was deleted: Deleting all affected analyses..."
    )
    Analysis.objects.filter(subject_dispatch__surface=instance.surface).delete()
