import logging

from rest_framework import serializers

import topobank.taskapp.serializers

from ..supplib.serializers import StrictFieldMixin
from .models import Analysis, AnalysisFunction, AnalysisSubject, Configuration
from .registry import get_visualization_type_for_function_name

_log = logging.getLogger(__name__)


class ConfigurationSerializer(StrictFieldMixin, serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Configuration
        fields = ["valid_since", "versions"]

    versions = serializers.SerializerMethodField()

    def get_versions(self, obj):
        versions = {}
        for version in obj.versions.all():
            versions[str(version.dependency)] = version.number_as_string()
        return versions


class AnalysisFunctionSerializer(
    StrictFieldMixin, serializers.HyperlinkedModelSerializer
):
    class Meta:
        model = AnalysisFunction
        fields = ["id", "url", "name", "visualization_app_name", "visualization_type"]

    url = serializers.HyperlinkedIdentityField(
        view_name="analysis:function-detail", read_only=True
    )

    visualization_app_name = serializers.SerializerMethodField()
    visualization_type = serializers.SerializerMethodField()

    def get_visualization_app_name(self, obj):
        app_name, type = get_visualization_type_for_function_name(
            obj.name
        )
        return app_name

    def get_visualization_type(self, obj):
        app_name, type = get_visualization_type_for_function_name(
            obj.name
        )
        return type


class AnalysisSubjectSerializer(
    StrictFieldMixin, serializers.HyperlinkedModelSerializer
):
    class Meta:
        model = AnalysisSubject
        fields = ["id", "tag", "topography", "surface"]

    tag = serializers.HyperlinkedRelatedField(
        view_name="manager:tag-api-detail", read_only=True
    )
    topography = serializers.HyperlinkedRelatedField(
        view_name="manager:topography-api-detail", read_only=True
    )
    surface = serializers.HyperlinkedRelatedField(
        view_name="manager:surface-api-detail", read_only=True
    )


class AnalysisResultSerializer(
    StrictFieldMixin, topobank.taskapp.serializers.TaskStateModelSerializer
):
    class Meta:
        model = Analysis
        fields = [
            "id",
            "url",
            "function",
            "subject",
            "kwargs",
            "task_progress",
            "task_state",
            "task_memory",
            "creation_time",
            "start_time",
            "end_time",
            "dois",
            "configuration",
            "duration",
            "error",
            "folder",
        ]

    url = serializers.HyperlinkedIdentityField(
        view_name="analysis:result-detail", read_only=True
    )
    function = serializers.HyperlinkedRelatedField(
        view_name="analysis:function-detail", read_only=True
    )
    subject = AnalysisSubjectSerializer(source="subject_dispatch")
    folder = serializers.HyperlinkedRelatedField(
        view_name="files:folder-api-detail", read_only=True
    )
    configuration = serializers.HyperlinkedRelatedField(
        view_name="analysis:configuration-detail", read_only=True
    )
