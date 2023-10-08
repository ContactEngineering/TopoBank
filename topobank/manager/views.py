import logging
import os.path
from io import BytesIO

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.http import HttpResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, TemplateView, FormView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.contrib import messages
from django.utils.text import slugify

from guardian.decorators import permission_required_or_403
from guardian.shortcuts import assign_perm, get_users_with_perms, remove_perm

from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from trackstats.models import Metric, Period

import topobank.taskapp.utils

from ..usage_stats.utils import increase_statistics_by_date, increase_statistics_by_date_and_object
from ..publication.models import MAX_LEN_AUTHORS_FIELD
from ..users.models import User

from .containers import write_surface_container
from .forms import SurfaceForm, SurfacePublishForm
from .models import Topography, Surface, TagModel, NewPublicationTooFastException, PublicationException, \
    topography_datafile_path
from .permissions import ObjectPermissions, ParentObjectPermissions, api_to_guardian
from .serializers import SurfaceSerializer, TopographySerializer, TagSearchSerizalizer, SurfaceSearchSerializer
from .utils import selected_instances, tags_for_user, current_selection_as_basket_items, filtered_surfaces, \
    filtered_topographies, get_search_term, get_category, get_sharing_status, get_tree_mode, \
    s3_post

# create dicts with labels and option values for Select tab
CATEGORY_FILTER_CHOICES = {'all': 'All categories',
                           **{cc[0]: cc[1] + " only" for cc in Surface.CATEGORY_CHOICES}}
SHARING_STATUS_FILTER_CHOICES = {
    'all': 'All accessible surfaces',
    'own': 'Only own surfaces',
    'shared': 'Only surfaces shared with you',
    'published': 'Only surfaces published by anyone',
}
TREE_MODE_CHOICES = ['surface list', 'tag tree']

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 10

DEFAULT_SELECT_TAB_STATE = {
    'search_term': '',  # empty string means: no search
    'category': 'all',
    'sharing_status': 'all',
    'tree_mode': 'surface list',
    'page_size': 10,
    'current_page': 1,
    # all these values are the default if no filter has been applied
    # and the page is loaded the first time
}

MEASUREMENT_TIME_INFO_FIELD = 'acquisition_time'

DEFAULT_CONTAINER_FILENAME = "digital_surface_twin.zip"

_log = logging.getLogger(__name__)

surface_view_permission_required = method_decorator(
    permission_required_or_403('manager.view_surface', ('manager.Surface', 'pk', 'pk'))
    # translates to:
    #
    # In order to access, a specific permission is required. This permission
    # is 'view_surface' for a specific surface. Which surface? This is calculated
    # from view argument 'pk' (the last element in tuple), which is used to get a
    # 'manager.Surface' instance (first element in tuple) with field 'pk' with same value as
    # last element in tuple (the view argument 'pk').
    #
    # Or in pseudocode:
    #
    #  s = Surface.objects.get(pk=view.kwargs['pk'])
    #  assert request.user.has_perm('view_surface', s)
)

surface_update_permission_required = method_decorator(
    permission_required_or_403('manager.change_surface', ('manager.Surface', 'pk', 'pk'))
)

surface_delete_permission_required = method_decorator(
    permission_required_or_403('manager.delete_surface', ('manager.Surface', 'pk', 'pk'))
)

surface_share_permission_required = method_decorator(
    permission_required_or_403('manager.share_surface', ('manager.Surface', 'pk', 'pk'))
)

surface_publish_permission_required = method_decorator(
    permission_required_or_403('manager.publish_surface', ('manager.Surface', 'pk', 'pk'))
)


class TopographyPermissionMixin(UserPassesTestMixin):
    redirect_field_name = None

    def has_surface_permissions(self, perms):
        if 'pk' not in self.kwargs:
            return True

        try:
            topo = Topography.objects.get(pk=self.kwargs['pk'])
        except Topography.DoesNotExist:
            raise Http404()

        return all(self.request.user.has_perm(perm, topo.surface)
                   for perm in perms)

    def test_func(self):
        return NotImplementedError()


class TopographyViewPermissionMixin(TopographyPermissionMixin):
    def test_func(self):
        return self.has_surface_permissions(['view_surface'])


class TopographyUpdatePermissionMixin(TopographyPermissionMixin):
    def test_func(self):
        return self.has_surface_permissions(['view_surface', 'change_surface'])


class ORCIDUserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return not self.request.user.is_anonymous


class TopographyDetailView(TemplateView):
    template_name = "manager/topography_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get surface instance
        topography_id = self.request.GET.get('topography')
        if topography_id is None:
            return context
        topography = Topography.objects.get(id=int(topography_id))

        #
        # Add context needed for tabs
        #
        context['extra_tabs'] = [
            {
                'title': f"{topography.surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={topography.surface.pk}",
                'active': False,
                'login_required': False,
                'tooltip': f"Properties of surface '{topography.surface.label}'"
            },
            {
                'title': f"{topography.name}",
                'icon': "file",
                'icon_style_prefix': 'far',
                'href': self.request.path,
                'active': True,
                'login_required': False,
                'tooltip': f"Properties of topography '{topography.name}'"
            }
        ]

        return context


class SelectView(TemplateView):
    template_name = "manager/select.html"

    def dispatch(self, request, *args, **kwargs):
        # count this view event for statistics
        metric = Metric.objects.SEARCH_VIEW_COUNT
        increase_statistics_by_date(metric, period=Period.DAY)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        session = self.request.session

        search_term = get_search_term(self.request)
        if search_term:
            # When searching, we want the default select tab state except for
            # the search term, which is taken from thr request parameters.
            # If not using the default select tab state, this can result
            # in "Load Error!" on the page (#543) because e.g. page 2
            # is not available in the result.
            select_tab_state = DEFAULT_SELECT_TAB_STATE.copy()
            select_tab_state['search_term'] = search_term
        else:
            # .. otherwise keep search term from session variable 'select_tab_state'
            #    and all other state settings
            select_tab_state = session.get('select_tab_state',
                                           default=DEFAULT_SELECT_TAB_STATE.copy())

        # key: tree mode
        context['base_urls'] = {
            'surface list': self.request.build_absolute_uri(reverse('manager:search')),
            'tag tree': self.request.build_absolute_uri(reverse('manager:tag-list')),
        }

        context['category_filter_choices'] = CATEGORY_FILTER_CHOICES.copy()

        if self.request.user.is_anonymous:
            # Anonymous user have only one choice
            context['sharing_status_filter_choices'] = {
                'published': SHARING_STATUS_FILTER_CHOICES['published']
            }
            select_tab_state['sharing_status'] = 'published'  # this only choice should be selected
        else:
            context['sharing_status_filter_choices'] = SHARING_STATUS_FILTER_CHOICES.copy()

        context['select_tab_state'] = select_tab_state.copy()

        # The session needs a default for the state of the select tab
        session['select_tab_state'] = select_tab_state

        return context


class SurfaceCreateView(ORCIDUserRequiredMixin, CreateView):
    model = Surface
    form_class = SurfaceForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['autocomplete_tags'] = tags_for_user(self.request.user)
        return kwargs

    def get_initial(self, *args, **kwargs):
        initial = super(SurfaceCreateView, self).get_initial()
        initial = initial.copy()
        initial['creator'] = self.request.user
        return initial

    def get_success_url(self):
        return f"{reverse('manager:surface-detail')}?surface={self.object.pk}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['extra_tabs'] = [
            {
                'title': f"Create surface",
                'icon': "plus-square",
                'icon_style_prefix': 'far',
                'href': self.request.path,
                'active': True,
                'tooltip': "Creating a new surface"
            }
        ]
        return context


class SurfaceDetailView(TemplateView):
    template_name = "manager/surface_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get surface instance
        surface_id = self.request.GET.get('surface')
        if surface_id is None:
            return context
        surface = Surface.objects.get(id=int(surface_id))

        context['extra_tabs'] = [
            {
                'title': f"{surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            }
        ]

        return context


class SurfacePublishView(FormView):
    template_name = "manager/surface_publish.html"
    form_class = SurfacePublishForm

    @surface_publish_permission_required
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, *kwargs)

    def _get_surface(self):
        surface_pk = self.kwargs['pk']
        return Surface.objects.get(pk=surface_pk)

    def get_initial(self):
        initial = super().get_initial()
        initial['author_0'] = ''
        initial['num_author_fields'] = 1
        return initial

    # def get_form_kwargs(self):
    #     kwargs = super().get_form_kwargs()
    #     if self.request.method == 'POST':
    #         # The field 'num_author_fields' may have been increased by
    #         # Javascript (Vuejs) on the client in order to add new authors.
    #         # This should be sent to the form in order to know
    #         # how many fields the form should have and how many author names
    #         # should be combined. So this is passed here:
    #         kwargs['num_author_fields'] = int(self.request.POST.get('num_author_fields'))
    #     return kwargs

    def get_success_url(self):
        return reverse('manager:publications')

    def form_valid(self, form):
        license = form.cleaned_data.get('license')
        authors = form.cleaned_data.get('authors_json')
        surface = self._get_surface()
        try:
            surface.publish(license, authors)
        except NewPublicationTooFastException as exc:
            return redirect("manager:surface-publication-rate-too-high",
                            pk=surface.pk)
        except PublicationException as exc:
            msg = f"Publication failed, reason: {exc}"
            _log.error(msg)
            messages.error(self.request, msg)
            return redirect("manager:surface-publication-error",
                            pk=surface.pk)

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        surface = self._get_surface()

        context['extra_tabs'] = [
            {
                'title': f"{surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            },
            {
                'title': f"Publish surface?",
                'icon': "bullhorn",
                'href': self.request.path,
                'active': True,
                'tooltip': f"Publishing surface '{surface.label}'"
            }
        ]
        context['surface'] = surface
        context['max_len_authors_field'] = MAX_LEN_AUTHORS_FIELD
        user = self.request.user
        context['user_dict'] = dict(
            first_name=user.first_name,
            last_name=user.last_name,
            orcid_id=user.orcid_id
        )
        context['configured_for_doi_generation'] = settings.PUBLICATION_DOI_MANDATORY
        return context


class PublicationRateTooHighView(TemplateView):
    template_name = "manager/publication_rate_too_high.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['min_seconds'] = settings.MIN_SECONDS_BETWEEN_SAME_SURFACE_PUBLICATIONS

        surface_pk = self.kwargs['pk']
        surface = Surface.objects.get(pk=surface_pk)

        context['extra_tabs'] = [
            {
                'title': f"{surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            },
            {
                'title': f"Publication rate too high",
                'icon': "flash",
                'href': self.request.path,
                'active': True,
            }
        ]
        return context


class PublicationErrorView(TemplateView):
    template_name = "manager/publication_error.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        surface_pk = self.kwargs['pk']
        surface = Surface.objects.get(pk=surface_pk)

        context['extra_tabs'] = [
            {
                'title': f"{surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            },
            {
                'title': f"Publication error",
                'icon': "flash",
                'href': self.request.path,
                'active': True,
            }
        ]
        return context


def download_surface(request, surface_id):
    """Returns a file comprised from topographies contained in a surface.

    :param request:
    :param surface_id: surface id
    :return:
    """

    #
    # Check existence and permissions for given surface
    #
    try:
        surface = Surface.objects.get(id=surface_id)
    except Surface.DoesNotExist:
        raise PermissionDenied()

    if not request.user.has_perm('view_surface', surface):
        raise PermissionDenied()

    content_data = None

    #
    # If the surface has been published, there might be a container file already.
    # If yes:
    #   Is there already a container?
    #     Then it instead of creating a new container.from
    #     If no, save the container in the publication later.
    # If no: create a container for this surface on the fly
    #
    renew_publication_container = False
    if surface.is_published:
        pub = surface.publication
        container_filename = os.path.basename(pub.container_storage_path)

        # noinspection PyBroadException
        try:
            with pub.container.open() as cf:
                content_data = cf.read()
            _log.debug(f"Read container for published surface {pub.short_url} from storage.")
        except Exception:  # not interested here, why it fails
            renew_publication_container = True
    else:
        container_filename = slugify(surface.name) + ".zip"

    if content_data is None:
        container_bytes = BytesIO()
        _log.info(f"Preparing container of surface id={surface_id} for download..")
        write_surface_container(container_bytes, [surface])
        content_data = container_bytes.getvalue()

        if renew_publication_container:
            try:
                container_bytes.seek(0)
                _log.info(f"Saving container for publication with URL {pub.short_url} to storage for later..")
                pub.container.save(pub.container_storage_path, container_bytes)
            except (OSError, BlockingIOError) as exc:
                _log.error(f"Cannot save container for publication {pub.short_url} to storage. "
                           f"Reason: {exc}")

    # Prepare response object.
    response = HttpResponse(content_data,
                            content_type='application/x-zip-compressed')
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(container_filename)

    increase_statistics_by_date_and_object(Metric.objects.SURFACE_DOWNLOAD_COUNT,
                                           period=Period.DAY, obj=surface)

    return response


def download_selection_as_surfaces(request):
    """Returns a file comprised from surfaces related to the selection.

    :param request: current request
    :return:
    """

    from .utils import current_selection_as_surface_list
    surfaces = current_selection_as_surface_list(request)

    container_bytes = BytesIO()
    write_surface_container(container_bytes, surfaces)

    # Prepare response object.
    response = HttpResponse(container_bytes.getvalue(),
                            content_type='application/x-zip-compressed')
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(DEFAULT_CONTAINER_FILENAME)
    # Since the selection contains multiple surfaces in general, we should think about
    # another file name in this case.

    # increase download count for each surface
    for surf in surfaces:
        increase_statistics_by_date_and_object(Metric.objects.SURFACE_DOWNLOAD_COUNT,
                                               period=Period.DAY, obj=surf)

    return response


#######################################################################################
# Views for REST interface
#######################################################################################
class SurfaceSearchPaginator(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_query_param = 'page'
    page_size_query_param = 'page_size'
    max_page_size = MAX_PAGE_SIZE

    def get_paginated_response(self, data):

        #
        # Save information about requested data in session
        #
        session = self.request.session

        select_tab_state = session.get('select_tab_state', DEFAULT_SELECT_TAB_STATE.copy())
        # not using the keyword argument "default" here, because in some tests,
        # the session is a simple dict and no real session dict. A simple
        # dict's .get() has no keyword argument 'default', although it can be given
        # as second parameter.

        select_tab_state['search_term'] = get_search_term(self.request)
        select_tab_state['category'] = get_category(self.request)
        select_tab_state['sharing_status'] = get_sharing_status(self.request)
        select_tab_state['tree_mode'] = get_tree_mode(self.request)
        page_size = self.get_page_size(self.request)
        select_tab_state[self.page_size_query_param] = page_size
        select_tab_state['current_page'] = self.page.number
        _log.debug("Setting select tab state set in paginator: %s", select_tab_state)
        session['select_tab_state'] = select_tab_state

        return Response({
            'num_items': self.page.paginator.count,
            'num_pages': self.page.paginator.num_pages,
            'page_range': list(self.page.paginator.page_range),
            'page_urls': list(self.get_page_urls()),
            'current_page': self.page.number,
            'num_items_on_current_page': len(self.page.object_list),
            'page_size': page_size,
            'search_term': select_tab_state['search_term'],
            'category': select_tab_state['category'],
            'sharing_status': select_tab_state['sharing_status'],
            'tree_mode': select_tab_state['tree_mode'],
            'page_results': data
        })

    def get_page_urls(self):
        base_url = self.request.build_absolute_uri()
        urls = []
        for page_no in self.page.paginator.page_range:
            if page_no == 1:
                url = remove_query_param(base_url, self.page_query_param)
            else:
                url = replace_query_param(base_url, self.page_query_param, page_no)
            # always add page size, so requests for other pages have it
            url = replace_query_param(url, self.page_size_query_param, self.get_page_size(self.request))
            urls.append(url)
        return urls


class TagTreeView(generics.ListAPIView):
    """
    Generate tree of tags with surfaces and topographies underneath.
    """
    serializer_class = TagSearchSerizalizer
    pagination_class = SurfaceSearchPaginator

    def get_queryset(self):
        surfaces = filtered_surfaces(self.request)
        topographies = filtered_topographies(self.request, surfaces)
        return tags_for_user(self.request.user, surfaces, topographies).filter(parent=None)
        # Only top level are collected, the children are added in the serializer.
        #
        # TODO The filtered surfaces and topographies are calculated twice here, not sure how to circumvent this.
        # Maybe by caching with request argument?

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['selected_instances'] = selected_instances(self.request)
        context['request'] = self.request

        surfaces = filtered_surfaces(self.request)
        topographies = filtered_topographies(self.request, surfaces)
        tags = tags_for_user(self.request.user, surfaces, topographies)
        context['tags_for_user'] = tags

        #
        # also pass filtered surfaces and topographies the user has access to
        #
        context['surfaces'] = surfaces
        context['topographies'] = topographies

        return context


# FIXME!!! This should be folded into the `SurfaceViewSet`, but handling
#  selections should be moved to the client first.
class SurfaceListView(generics.ListAPIView):
    """
    List all surfaces with topographies underneath.
    """
    serializer_class = SurfaceSearchSerializer
    pagination_class = SurfaceSearchPaginator

    def get_queryset(self):
        return filtered_surfaces(self.request)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['selected_instances'] = selected_instances(self.request)
        context['request'] = self.request
        return context


def _selection_set(request):
    return set(request.session.get('selection', []))


def _surface_key(pk):  # TODO use such a function everywhere: instance_key_for_selection()
    return 'surface-{}'.format(pk)


def _topography_key(pk):
    return 'topography-{}'.format(pk)


def _tag_key(pk):
    return 'tag-{}'.format(pk)


def set_surface_select_status(request, pk, select_status):
    """Marks the given surface as 'selected' in session or checks this.

        :param request: request
        :param pk: primary key of the surface
        :param select_status: True if surface should be selected, False if it should be unselected
        :return: JSON Response

        The response returns the current selection as suitable for the basket.
    """
    try:
        pk = int(pk)
        surface = Surface.objects.get(pk=pk)
        assert request.user.has_perm('view_surface', surface)
    except (ValueError, Surface.DoesNotExist, AssertionError):
        raise PermissionDenied()  # This should be shown independent of whether the surface exists

    surface_key = _surface_key(pk)
    selection = _selection_set(request)
    is_selected = surface_key in selection

    if request.method == 'POST':
        if select_status:
            # surface should be selected
            selection.add(surface_key)
        elif is_selected:
            selection.remove(surface_key)

        request.session['selection'] = list(selection)

    data = current_selection_as_basket_items(request)
    return Response(data)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def select_surface(request, pk):
    """Marks the given surface as 'selected' in session.

    :param request: request
    :param pk: primary key of the surface
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_surface_select_status(request, pk, True)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def unselect_surface(request, pk):
    """Marks the given surface as 'unselected' in session.

    :param request: request
    :param pk: primary key of the surface
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_surface_select_status(request, pk, False)


def set_topography_select_status(request, pk, select_status):
    """Marks the given topography as 'selected' or 'unselected' in session.

    :param request: request
    :param pk: primary key of the surface
    :param select_status: True or False, True means "mark as selected", False means "mark as unselected"
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    try:
        pk = int(pk)
        topo = Topography.objects.get(pk=pk)
        assert request.user.has_perm('view_surface', topo.surface)
    except (ValueError, Topography.DoesNotExist, AssertionError):
        raise PermissionDenied()  # This should be shown independent of whether the surface exists

    topography_key = _topography_key(pk)
    selection = _selection_set(request)
    is_selected = topography_key in selection

    if request.method == 'POST':
        if select_status:
            # topography should be selected
            selection.add(topography_key)
        elif is_selected:
            selection.remove(topography_key)

        request.session['selection'] = list(selection)

    data = current_selection_as_basket_items(request)
    return Response(data)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def select_topography(request, pk):
    """Marks the given topography as 'selected' in session.

    :param request: request
    :param pk: primary key of the surface
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_topography_select_status(request, pk, True)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def unselect_topography(request, pk):
    """Marks the given topography as 'selected' in session.

    :param request: request
    :param pk: primary key of the surface
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_topography_select_status(request, pk, False)


def set_tag_select_status(request, pk, select_status):
    """Marks the given tag as 'selected' in session or checks this.

        :param request: request
        :param pk: primary key of the tag
        :param select_status: True if tag should be selected, False if it should be unselected
        :return: JSON Response

        The response returns the current selection as suitable for the basket.
    """
    try:
        pk = int(pk)
        tag = TagModel.objects.get(pk=pk)
    except ValueError:
        raise PermissionDenied()

    if not tag in tags_for_user(request.user):
        raise PermissionDenied()

    tag_key = _tag_key(pk)
    selection = _selection_set(request)
    is_selected = tag_key in selection

    if request.method == 'POST':
        if select_status:
            # tag should be selected
            selection.add(tag_key)
        elif is_selected:
            selection.remove(tag_key)

        request.session['selection'] = list(selection)

    data = current_selection_as_basket_items(request)
    return Response(data)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def select_tag(request, pk):
    """Marks the given tag as 'selected' in session.

    :param request: request
    :param pk: primary key of the tag
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_tag_select_status(request, pk, True)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def unselect_tag(request, pk):
    """Marks the given tag as 'unselected' in session.

    :param request: request
    :param pk: primary key of the tag
    :return: JSON Response

    The response returns the current selection as suitable for the basket.
    """
    return set_tag_select_status(request, pk, False)


@api_view(['POST'])
@permission_classes([])  # We need to override permissions because the anonymous user has read-only access
def unselect_all(request):
    """Removes all selections from session.

    :param request: request
    :return: empty list as JSON Response
    """
    request.session['selection'] = []
    return Response([])


def dzi(request, pk, dzi_filename):
    """Returns deepzoom image data for a topography

    Parameters
    ----------
    request

    Returns
    -------
    HTML Response with image data
    """
    try:
        pk = int(pk)
    except ValueError:
        raise Http404()

    try:
        topo = Topography.objects.get(pk=pk)
    except Topography.DoesNotExist:
        raise Http404()

    if not request.user.has_perm('view_surface', topo.surface):
        raise PermissionDenied()

    # okay, we have a valid topography and the user is allowed to see it

    return redirect(default_storage.url(f'{topo.storage_prefix}/dzi/{dzi_filename}'))


class SurfaceViewSet(mixins.CreateModelMixin,
                     mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin,
                     viewsets.GenericViewSet):
    queryset = Surface.objects.prefetch_related('topography_set')
    serializer_class = SurfaceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, ObjectPermissions]

    def perform_create(self, serializer):
        # Set creator to current user when creating a new surface
        serializer.save(creator=self.request.user)


class TopographyViewSet(mixins.CreateModelMixin,
                        mixins.UpdateModelMixin,
                        mixins.DestroyModelMixin,
                        viewsets.GenericViewSet):
    EXPIRE_UPLOAD = 10  # Presigned key for uploading expires after 10 second

    queryset = Topography.objects.all()
    serializer_class = TopographySerializer
    permission_classes = [IsAuthenticatedOrReadOnly, ParentObjectPermissions]

    def perform_create(self, serializer):
        # File name is passed in the 'name' field on create. It is the only field that needs to be present for the
        # create (POST) request.
        filename = self.request.data['name']

        # Set creator to current user when creating a new topography
        instance = serializer.save(creator=self.request.user)

        # Now we have an id, so populate update path
        datafile_path = topography_datafile_path(instance, filename)

        # Populate upload_url, the presigned key should expire quickly
        serializer.update(instance, {'post_data': s3_post(datafile_path, self.EXPIRE_UPLOAD)})

    # From mixins.RetrieveModelMixin
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _log.debug(instance.measurement_date)
        if instance.task_state == Topography.NOTRUN:
            # The cache has never been created
            _log.info(f"Creating cached properties of new {instance.get_subject_type()} {instance.id}...")
            topobank.taskapp.utils.run_task(instance)
            instance.save()  # run_task sets the initial task state to 'pe', so we need to save
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


@api_view(['PATCH'])
def set_permissions(request, pk=None):
    user = request.user
    obj = Surface.objects.get(pk=pk)

    # Check that user has the right to modify permissions
    if not user.has_perms(['view_surface', 'change_surface', 'delete_surface', 'share_surface', 'publish_surface'],
                          obj):
        return HttpResponseForbidden()

    # Check that the request does not ask to revoke permissions from the current user
    for permission in request.data:
        if permission['user']['id'] == user.id:
            if permission['permission'] != 'full':
                return Response({'message': 'Permissions cannot be revoked from logged in user'},
                                status=405)  # Not allowed

    # Get all current object permissions
    users_with_perms = {user.id: perms for user, perms in get_users_with_perms(obj, attach_perms=True).items()}

    # Everything looks okay, update permissions
    for permission in request.data:
        user_id = permission['user']['id']
        if user_id != user.id:
            other_user = User.objects.get(id=user_id)

            # Get current set of permissions and new permissions
            try:
                current_perms = set(users_with_perms[user_id])
            except KeyError:
                current_perms = set()
            new_perms = set(api_to_guardian(permission['permission']))

            # Assign all perms that are in the new set but not in the old
            for perm in new_perms - current_perms:
                assign_perm(perm, other_user, obj)

            # Remove all perms that are in the old set but not in the new
            for perm in current_perms - new_perms:
                remove_perm(perm, other_user, obj)

    # Permissions were updated successfully
    return Response({}, status=204)
