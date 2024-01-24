import logging

from django.utils.translation import gettext_lazy as _

from guardian.shortcuts import get_users_with_perms
from rest_framework import serializers
from tagulous.contrib.drf import TagRelatedManagerField

from ..taskapp.serializers import TaskStateModelSerializer
from ..users.serializers import UserSerializer

from .models import Property, Surface, Topography
from .utils import guardian_to_api

_log = logging.getLogger(__name__)


# From: RomanKhudobei, https://github.com/encode/django-rest-framework/issues/1655
class StrictFieldMixin:
    """Raises error if read only fields or non-existing fields passed to input data"""
    default_error_messages = {
        'read_only': _('This field is read only'),
        'does_not_exist': _('This field does not exist')
    }

    def to_internal_value(self, data):
        field_names = set(field.field_name for field in self._writable_fields)
        errors = {}

        # check that all dictionary keys are fields
        for key in data.keys():
            if key not in field_names:
                errors[key] = serializers.ErrorDetail(self.error_messages['does_not_exist'], code='does_not_exist')

        if errors != {}:
            raise serializers.ValidationError(errors)

        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if not hasattr(self, 'initial_data'):
            return attrs

        # collect declared read only fields and read only fields from Meta
        read_only_fields = ({field_name for field_name, field in self.fields.items() if field.read_only} |
                            set(getattr(self.Meta, 'read_only_fields', set())))

        received_read_only_fields = set(self.initial_data) & read_only_fields

        if received_read_only_fields:
            errors = {}
            for field_name in received_read_only_fields:
                errors[field_name] = serializers.ErrorDetail(self.error_messages['read_only'], code='read_only')

            raise serializers.ValidationError(errors)

        return attrs


class TopographySerializer(StrictFieldMixin,
                           TaskStateModelSerializer):
    class Meta:
        model = Topography
        fields = ['url',
                  'id',
                  'surface',
                  'name',
                  'creator',
                  'datafile', 'datafile_format', 'channel_names', 'data_source',
                  'squeezed_datafile',
                  'description',
                  'measurement_date',
                  'size_editable', 'size_x', 'size_y',
                  'unit_editable', 'unit',
                  'height_scale_editable', 'height_scale',
                  'has_undefined_data', 'fill_undefined_data_mode',
                  'detrend_mode',
                  'resolution_x', 'resolution_y',
                  'bandwidth_lower', 'bandwidth_upper',
                  'short_reliability_cutoff',
                  'is_periodic_editable', 'is_periodic',
                  'instrument_name', 'instrument_type', 'instrument_parameters',
                  'upload_instructions',
                  'is_metadata_complete',
                  'thumbnail',
                  'creation_datetime', 'modification_datetime',
                  'duration', 'error', 'task_progress', 'task_state', 'tags',  # TaskStateModelSerializer
                  'permissions']

    url = serializers.HyperlinkedIdentityField(view_name='manager:topography-api-detail', read_only=True)
    creator = serializers.HyperlinkedRelatedField(view_name='users:user-api-detail', read_only=True)
    surface = serializers.HyperlinkedRelatedField(view_name='manager:surface-api-detail',
                                                  queryset=Surface.objects.all())

    tags = TagRelatedManagerField(required=False)

    is_metadata_complete = serializers.SerializerMethodField()

    upload_instructions = serializers.DictField(default=None, read_only=True)  # Pre-signed upload location

    permissions = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We only return permissions if requested to do so
        with_permissions = False
        if 'request' in self.context:
            permissions = self.context['request'].query_params.get('permissions')
            with_permissions = permissions is not None and permissions.lower() in ['yes', 'true']
        if not with_permissions:
            self.fields.pop('permissions')

    def validate(self, data):
        read_only_fields = []
        if self.instance is not None:
            if not self.instance.size_editable:
                if 'size_x' in data:
                    read_only_fields += ['size_x']
                if 'size_y' in data:
                    read_only_fields += ['size_y']
            if not self.instance.unit_editable:
                if 'unit' in data:
                    read_only_fields += ['unit']
            if not self.instance.height_scale_editable:
                if 'unit' in data:
                    read_only_fields += ['height_scale']
            if not self.instance.is_periodic_editable:
                if 'is_periodic' in data:
                    read_only_fields += ['is_periodic']
            if len(read_only_fields) > 0:
                s = ', '.join([f'`{name}`' for name in read_only_fields])
                raise serializers.ValidationError(f'{s} is given by the data file and cannot be set')
        return super().validate(data)

    def get_is_metadata_complete(self, obj):
        return obj.is_metadata_complete

    def get_permissions(self, obj):
        request = self.context['request']
        current_user = request.user
        users = get_users_with_perms(obj.surface, attach_perms=True)
        return {'current_user': {'user': UserSerializer(current_user, context=self.context).data,
                                 'permission': guardian_to_api(users[current_user])},
                'other_users': [{'user': UserSerializer(key, context=self.context).data,
                                 'permission': guardian_to_api(value)}
                                for key, value in users.items() if key != current_user]}


class PropertySerializer(StrictFieldMixin, serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Property
        fields = ['name', 'value_categorical', 'value_numerical', 'unit']

    name = serializers.CharField()
    unit = serializers.CharField()


class SurfaceSerializer(StrictFieldMixin,
                        serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Surface
        fields = ['url',
                  'id',
                  'name',
                  'category',
                  'creator',
                  'description',
                  'tags',
                  'creation_datetime', 'modification_datetime',
                  'topography_set',
                  'permissions',
                  'properties']

    url = serializers.HyperlinkedIdentityField(view_name='manager:surface-api-detail', read_only=True)
    creator = serializers.HyperlinkedRelatedField(view_name='users:user-api-detail', read_only=True)
    topography_set = TopographySerializer(many=True, read_only=True)

    tags = TagRelatedManagerField(required=False)

    permissions = serializers.SerializerMethodField()

    properties = PropertySerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We only return the topography set if requested to do so
        children = self.context['request'].query_params.get('children')
        with_children = children is not None and children.lower() in ['yes', 'true']
        if not with_children:
            self.fields.pop('topography_set')

        # We only return permissions if requested to do so
        permissions = self.context['request'].query_params.get('permissions')
        with_permissions = permissions is not None and permissions.lower() in ['yes', 'true']
        if not with_permissions:
            self.fields.pop('permissions')

    def get_permissions(self, obj):
        request = self.context['request']
        current_user = request.user
        users = get_users_with_perms(obj, attach_perms=True)
        return {'current_user': {'user': UserSerializer(current_user, context=self.context).data,
                                 'permission': guardian_to_api(users[current_user])},
                'other_users': [{'user': UserSerializer(key, context=self.context).data,
                                 'permission': guardian_to_api(value)}
                                for key, value in users.items() if key != current_user]}
