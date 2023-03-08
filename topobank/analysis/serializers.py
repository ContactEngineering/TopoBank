import logging
import pickle

from django.shortcuts import reverse

from rest_framework import serializers

from generic_relations.relations import GenericRelatedField

from ..manager.models import Surface, Topography
from ..manager.serializers import SurfaceSerializer, TopographySerializer
from .models import Analysis

_log = logging.getLogger(__name__)


class AnalysisSerializer(serializers.ModelSerializer):
    duration = serializers.SerializerMethodField()
    kwargs = serializers.SerializerMethodField()
    subject = GenericRelatedField({
        Surface: SurfaceSerializer(),
        Topography: TopographySerializer()
    })
    task_state = serializers.SerializerMethodField()
    task_progress = serializers.SerializerMethodField()
    urls = serializers.SerializerMethodField()

    def get_duration(self, obj):
        return obj.duration

    def get_kwargs(self, obj):
        return pickle.loads(obj.kwargs)

    def get_task_state(self, obj):
        # This is self-reported by the task runner
        self_reported_task_state = obj.task_state
        # This is what Celery reports back
        celery_task_state = obj.get_celery_state()

        if celery_task_state is None:
            # There is no Celery state, possibly because the Celery task has not yet been created
            return self_reported_task_state

        if self_reported_task_state == celery_task_state:
            # We're good!
            return self_reported_task_state
        else:
            if self_reported_task_state == Analysis.SUCCESS:
                # Something is wrong, but we return success if the task self-reports succes
                _log.info(f"The task with id {obj.id} self-reported the state '{self_reported_task_state}', "
                          f"but Celery reported '{celery_task_state}'. I am returning a success.")
                return Analysis.SUCCESS
            else:
                # We return a failure otherwise
                _log.info(f"The task with id {obj.id} self-reported the state '{self_reported_task_state}', "
                          f"but Celery reported '{celery_task_state}'. I am returning a failure.")
                return Analysis.FAILURE

    def get_task_progress(self, obj):
        if obj.task_state == Analysis.STARTED:
            return obj.get_task_progress()
        elif obj.task_state == Analysis.SUCCESS:
            return 1.0
        else:
            return 0.0

    def get_urls(self, obj):
        return {
            'status': reverse('analysis:status-detail', kwargs=dict(pk=obj.id))
        }

    class Meta:
        model = Analysis
        fields = ['id', 'function', 'subject', 'kwargs', 'task_progress', 'task_state', 'creation_time', 'start_time',
                  'end_time', 'dois', 'configuration', 'duration', 'urls']
        depth = 1
