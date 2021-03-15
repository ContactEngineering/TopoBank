from django.shortcuts import reverse
from django.db.models import Q

from rest_framework import serializers
from guardian.shortcuts import get_perms

import logging

from .models import Surface, Topography, TagModel
from .utils import get_search_term, get_category, get_sharing_status

_log = logging.getLogger(__name__)


class TopographySerializer(serializers.HyperlinkedModelSerializer):
    title = serializers.CharField(source='name')

    creator = serializers.HyperlinkedRelatedField(
        read_only=True,
        view_name='users:detail',
        lookup_field='username',
    )

    urls = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()
    surface_key = serializers.SerializerMethodField()
    folder = serializers.BooleanField(default=False)
    tags = serializers.SerializerMethodField()
    type = serializers.CharField(default='topography')
    version = serializers.CharField(default='')

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
            urls['analyze'] = reverse('analysis:topography', kwargs=dict(topography_id=obj.pk))

        if 'change_surface' in perms:
            urls.update({
                'update': reverse('manager:topography-update', kwargs=dict(pk=obj.pk))
            })

        if 'delete_surface' in perms:
            urls['delete'] = reverse('manager:topography-delete', kwargs=dict(pk=obj.pk))

        return urls

    def get_selected(self, obj):
        topographies, surfaces, tags = self.context['selected_instances']
        return obj in topographies

    def get_key(self, obj):
        return f"topography-{obj.pk}"

    def get_surface_key(self, obj):
        return f"surface-{obj.surface.pk}"

    def get_tags(self, obj):  # TODO prove if own method needed
        return [t.name for t in obj.tags.all()]

    class Meta:
        model = Topography
        fields = ['pk', 'type', 'name', 'creator', 'description', 'tags',
                  'urls', 'selected', 'key', 'surface_key', 'title', 'folder', 'version']


class SurfaceSerializer(serializers.HyperlinkedModelSerializer):
    title = serializers.CharField(source='name')
    # children = TopographySerializer(source='filtered_topographies', many=True, read_only=True)
    # children = TopographySerializer(source='topography_set', many=True, read_only=True)
    children = serializers.SerializerMethodField()

    creator = serializers.HyperlinkedRelatedField(
        read_only=True,
        view_name='users:detail',
        lookup_field='username',
    )

    urls = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()
    folder = serializers.BooleanField(default=True)
    sharing_status = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    type = serializers.CharField(default='surface')
    version = serializers.SerializerMethodField()

    def get_children(self, obj):
        #
        # We only want topographies as children which match the given search term,
        # if no search term is given, all topographies should be included, same, if the surface
        # itself matches
        #
        request = self.context['request']
        search_term = get_search_term(request)
        search_term_given = len(search_term) > 0
        search_term_lower = None if search_term is None else search_term.lower()
        topographies = obj.topography_set.all()

        obj_match = (not search_term_given) or (search_term_lower in obj.name.lower()) or \
                    (search_term_lower in obj.description.lower()) or \
                    (obj.tags.filter(name__icontains=search_term).count() > 0)

        # only filter topographies by search term if surface does not match search term
        if search_term_given and not obj_match:
            topographies = topographies.filter(Q(name__icontains=search_term) |
                                               Q(description__icontains=search_term) |
                                               Q(tags__name__icontains=search_term)).distinct()
        return TopographySerializer(topographies, many=True, context=self.context).data
        # TODO can filtered_topographies be used here instead?

    def get_urls(self, obj):

        user = self.context['request'].user
        perms = get_perms(user, obj)  # TODO are permissions needed here?

        urls = {
            'select': reverse('manager:surface-select', kwargs=dict(pk=obj.pk)),
            'unselect': reverse('manager:surface-unselect', kwargs=dict(pk=obj.pk))
        }
        if 'view_surface' in perms:
            urls['detail'] = reverse('manager:surface-detail', kwargs=dict(pk=obj.pk))
            if obj.num_topographies() > 0:
                urls.update({
                    'analyze': reverse('analysis:surface', kwargs=dict(surface_id=obj.id)),
                    'download': reverse('manager:surface-download', kwargs=dict(surface_id=obj.id)),

                })
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
        topographies, surfaces, tags = self.context['selected_instances']
        return obj in surfaces

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

    def get_tags(self, obj):
        return [t.name for t in obj.tags.all()]

    def get_version(self, obj):
        return obj.publication.version if obj.is_published else ''

    class Meta:
        model = Surface
        fields = ['pk', 'type', 'name', 'creator', 'description', 'category', 'tags', 'children',
                  'sharing_status', 'urls', 'selected', 'key', 'title', 'folder', 'version']


class TagSerializer(serializers.ModelSerializer):
    urls = serializers.SerializerMethodField()
    title = serializers.CharField(source='label')
    children = serializers.SerializerMethodField()
    folder = serializers.BooleanField(default=True)
    type = serializers.CharField(default='tag')
    key = serializers.SerializerMethodField()
    selected = serializers.SerializerMethodField()
    type = serializers.CharField(default='tag')
    version = serializers.CharField(default='')

    class Meta:
        model = TagModel
        fields = ['pk', 'key', 'type', 'title', 'name', 'children',
                  'folder', 'urls', 'selected', 'version']

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
        surfaces = self.context['surfaces'].filter(tags__pk=obj.pk).order_by('name')
        topographies = self.context['topographies'].filter(tags__pk=obj.pk).order_by('name')
        tags = [x for x in obj.children.all() if x in self.context['tags_for_user']]

        #
        # Serialize children and append to this tag
        #
        result.extend(TopographySerializer(topographies, many=True, context=self.context).data)
        result.extend(SurfaceSerializer(surfaces, many=True, context=self.context).data)
        result.extend(TagSerializer(tags, many=True, context=self.context).data)

        return result
