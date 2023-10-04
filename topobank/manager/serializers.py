import logging

from django.shortcuts import reverse
from guardian.shortcuts import get_perms
from rest_framework import serializers
from tagulous.contrib.drf import TagRelatedManagerField

from ..taskapp.serializers import TaskStateModelSerializer

from .models import Surface, Topography, TagModel
from .utils import get_search_term, filtered_topographies, subjects_to_base64

_log = logging.getLogger(__name__)


class TopographySerializer(TaskStateModelSerializer):
    class Meta:
        model = Topography
        fields = ['url',
                  'surface',
                  'name',
                  'creator',
                  'datafile_format', 'channel_names', 'data_source',
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
                  'is_periodic',
                  'instrument_name', 'instrument_type', 'instrument_parameters',
                  'post_data',
                  'is_metadata_complete',
                  'thumbnail',
                  'duration', 'error', 'task_progress', 'task_state', 'tags']  # TaskStateModelSerializer

    url = serializers.HyperlinkedIdentityField(view_name='manager:topography-api-detail', read_only=True)
    creator = serializers.HyperlinkedRelatedField(view_name='users:user-api-detail', read_only=True)
    surface = serializers.HyperlinkedRelatedField(view_name='manager:surface-api-detail',
                                                  queryset=Surface.objects.all())

    tags = TagRelatedManagerField(required=False)

    is_metadata_complete = serializers.SerializerMethodField()

    post_data = serializers.DictField(default=None, read_only=True)  # Pre-signed upload location

    def get_is_metadata_complete(self, obj):
        return obj.is_metadata_complete


class SurfaceSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Surface
        fields = ['url', 'name', 'category', 'creator', 'description', 'publication', 'tags', 'topography_set']

    url = serializers.HyperlinkedIdentityField(view_name='manager:surface-api-detail', read_only=True)
    creator = serializers.HyperlinkedRelatedField(view_name='users:user-api-detail', read_only=True)
    topography_set = TopographySerializer(many=True, read_only=True)

    tags = TagRelatedManagerField(required=False)


class TopographySearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topography
        fields = ['id', 'type', 'name', 'creator', 'description', 'tags', 'urls', 'selected', 'key', 'surface_key',
                  'title', 'folder', 'version', 'publication_date', 'publication_authors', 'datafile_format',
                  'measurement_date', 'resolution_x', 'resolution_y', 'size_x', 'size_y', 'size_editable', 'unit',
                  'unit_editable', 'height_scale', 'height_scale_editable', 'creator_name', 'sharing_status', 'label',
                  'is_periodic', 'thumbnail', 'tags', 'instrument_name', 'instrument_type', 'instrument_parameters']

    creator = serializers.HyperlinkedRelatedField(
        read_only=True,
        view_name='users:detail',
        lookup_field='username',
        default=serializers.CurrentUserDefault()
    )

    title = serializers.CharField(source='name', read_only=True)  # set this through name

    urls = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()
    surface_key = serializers.SerializerMethodField()
    sharing_status = serializers.SerializerMethodField()
    # `folder` is Fancytree-specific, see
    # https://wwwendt.de/tech/fancytree/doc/jsdoc/global.html#NodeData
    folder = serializers.BooleanField(default=False, read_only=True)
    tags = TagRelatedManagerField()
    # `type` should be the output of mangle_content_type(Meta.model)
    type = serializers.CharField(default='topography', read_only=True)
    version = serializers.CharField(default=None, read_only=True)
    publication_authors = serializers.CharField(default=None, read_only=True)
    publication_date = serializers.CharField(default=None, read_only=True)
    creator_name = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    def get_urls(self, obj):
        """Return only those urls which are usable for the user

        :param obj: topography object
        :return: dict with { url_name: url }
        """
        user = self.context['request'].user
        surface = obj.surface

        perms = get_perms(user, surface)  # TODO are permissions needed here?

        urls = {
            'select': reverse('manager:topography-select', kwargs=dict(pk=obj.pk)),
            'unselect': reverse('manager:topography-unselect', kwargs=dict(pk=obj.pk))
        }

        if 'view_surface' in perms:
            urls['detail'] = reverse('manager:topography-detail', kwargs=dict(pk=obj.pk))
            urls['analyze'] = f"{reverse('analysis:results-list')}?subjects={subjects_to_base64([obj])}"

        if 'change_surface' in perms:
            urls.update({
                'update': reverse('manager:topography-update', kwargs=dict(pk=obj.pk))
            })

        if 'delete_surface' in perms:
            urls['delete'] = reverse('manager:topography-delete', kwargs=dict(pk=obj.pk))

        return urls

    def get_selected(self, obj):
        try:
            topographies, surfaces, tags = self.context['selected_instances']
            return obj in topographies
        except KeyError:
            return False

    def get_key(self, obj):
        return f"topography-{obj.pk}"

    def get_surface_key(self, obj):
        return f"surface-{obj.surface.pk}"

    def get_sharing_status(self, obj):
        user = self.context['request'].user
        if hasattr(obj.surface, 'is_published') and obj.surface.is_published:
            return 'published'
        elif user == obj.surface.creator:
            return "own"
        else:
            return "shared"

    def get_creator_name(self, obj):
        return obj.creator.name

    def get_label(self, obj):
        return obj.label


class SurfaceSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Surface
        fields = ['id', 'type', 'name', 'creator', 'creator_name', 'description', 'category', 'category_name', 'tags',
                  'children', 'sharing_status', 'urls', 'selected', 'key', 'title', 'folder', 'version',
                  'publication_doi', 'publication_date', 'publication_authors', 'publication_license',
                  'topography_count', 'label']

    creator = serializers.HyperlinkedRelatedField(
        read_only=True,
        view_name='users:detail',
        lookup_field='username',
        default=serializers.CurrentUserDefault()
    )

    title = serializers.CharField(source='name')
    children = serializers.SerializerMethodField()

    urls = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()
    # `folder` is Fancytree-specific, see
    # https://wwwendt.de/tech/fancytree/doc/jsdoc/global.html#NodeData
    folder = serializers.BooleanField(default=True, read_only=True)
    sharing_status = serializers.SerializerMethodField()
    tags = TagRelatedManagerField()
    # `type` should be the output of mangle_content_type(Meta.model)
    type = serializers.CharField(default='surface', read_only=True)
    version = serializers.SerializerMethodField()
    publication_date = serializers.SerializerMethodField()
    publication_authors = serializers.SerializerMethodField()
    publication_license = serializers.SerializerMethodField()
    publication_doi = serializers.SerializerMethodField()
    topography_count = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    creator_name = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    def get_children(self, obj):
        """Get serialized topographies for given surface.

        Parameters
        ----------
        obj : Surface

        Returns
        -------

        """
        #
        # We only want topographies as children which match the given search term,
        # if no search term is given, all topographies should be included
        #
        request = self.context['request']
        search_term = get_search_term(request)
        search_term_given = len(search_term) > 0

        # only filter topographies by search term if surface does not match search term
        # otherwise list all topographies
        if search_term_given:
            topographies = filtered_topographies(request, [obj])
        else:
            topographies = obj.topography_set.all()
        return TopographySearchSerializer(topographies, many=True, context=self.context).data

    def get_urls(self, obj):

        user = self.context['request'].user
        perms = get_perms(user, obj)  # TODO are permissions needed here?

        urls = {
            'select': reverse('manager:surface-select', kwargs=dict(pk=obj.pk)),
            'unselect': reverse('manager:surface-unselect', kwargs=dict(pk=obj.pk))
        }
        if 'view_surface' in perms:
            urls['detail'] = f"{reverse('manager:surface-detail')}?surface={obj.pk}",
            if obj.num_topographies() > 0:
                urls.update({
                    'analyze': f"{reverse('analysis:results-list')}?subjects={subjects_to_base64([obj])}"
                })
            urls['download'] = reverse('manager:surface-download', kwargs=dict(surface_id=obj.id))

        if 'change_surface' in perms:
            urls.update({
                'add_topography': reverse('manager:topography-create', kwargs=dict(surface_id=obj.id)),
                'update': reverse('manager:surface-update', kwargs=dict(pk=obj.pk)),
            })
        if 'delete_surface' in perms:
            urls.update({
                'delete': reverse('manager:surface-delete', kwargs=dict(pk=obj.pk)),
            })
        if 'share_surface' in perms:
            urls.update({
                'share': reverse('manager:surface-share', kwargs=dict(pk=obj.pk)),
            })
        if 'publish_surface' in perms:
            urls.update({
                'publish': reverse('manager:surface-publish', kwargs=dict(pk=obj.pk)),
            })

        return urls

    def get_selected(self, obj):
        try:
            topographies, surfaces, tags = self.context['selected_instances']
            return obj in surfaces
        except KeyError:
            return False

    def get_key(self, obj):
        return f"surface-{obj.pk}"

    def get_sharing_status(self, obj):
        user = self.context['request'].user
        if hasattr(obj, 'is_published') and obj.is_published:
            return 'published'
        elif user == obj.creator:
            return "own"
        else:
            return "shared"

    def get_version(self, obj):
        return obj.publication.version if obj.is_published else None

    def get_publication_date(self, obj):
        return obj.publication.datetime.date() if obj.is_published else None

    def get_publication_authors(self, obj):
        return obj.publication.get_authors_string() if obj.is_published else None

    def get_publication_license(self, obj):
        return obj.publication.license if obj.is_published else None

    def get_publication_doi(self, obj):
        return obj.publication.doi_url if obj.is_published else None

    def get_topography_count(self, obj):
        return obj.topography_set.count()

    def get_category_name(self, obj):
        return obj.get_category_display()

    def get_creator_name(self, obj):
        return obj.creator.name

    def get_label(self, obj):
        return obj.label


class TagSearchSerizalizer(serializers.ModelSerializer):
    class Meta:
        model = TagModel
        fields = ['id', 'key', 'type', 'title', 'name', 'children', 'folder', 'urls', 'selected', 'version',
                  'publication_date', 'publication_authors', 'label']

    children = serializers.SerializerMethodField()
    # `folder` is Fancytree-specific, see
    # https://wwwendt.de/tech/fancytree/doc/jsdoc/global.html#NodeData
    folder = serializers.BooleanField(default=True, read_only=True)
    key = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    publication_authors = serializers.CharField(default=None, read_only=True)
    publication_date = serializers.CharField(default=None, read_only=True)
    selected = serializers.SerializerMethodField()
    title = serializers.CharField(source='label', read_only=True)
    # `type` should be the output of mangle_content_type(Meta.model)
    type = serializers.CharField(default='tag', read_only=True)
    urls = serializers.SerializerMethodField()
    version = serializers.CharField(default=None, read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._surface_serializer = SurfaceSerializer(context=self.context)
        self._topography_serializer = TopographySerializer(context=self.context)

    def get_urls(self, obj):
        urls = {
            'select': reverse('manager:tag-select', kwargs=dict(pk=obj.pk)),
            'unselect': reverse('manager:tag-unselect', kwargs=dict(pk=obj.pk))
        }
        return urls

    def get_key(self, obj):
        return f"tag-{obj.pk}"

    def get_selected(self, obj):
        topographies, surfaces, tags = self.context['selected_instances']
        return obj in tags

    def get_children(self, obj):
        result = []

        #
        # Assume that all surfaces and topographies given in the context are already filtered
        #
        surfaces = self.context['surfaces'].filter(tags__pk=obj.pk)  # .order_by('name')
        topographies = self.context['topographies'].filter(tags__pk=obj.pk)  # .order_by('name')
        tags = [x for x in obj.children.all() if x in self.context['tags_for_user']]

        #
        # Serialize children and append to this tag
        #
        result.extend(TopographySearchSerializer(topographies, many=True, context=self.context).data)
        result.extend(SurfaceSearchSerializer(surfaces, many=True, context=self.context).data)
        result.extend(TagSearchSerizalizer(tags, many=True, context=self.context).data)

        return result

    def get_label(self, obj):
        return obj.label
