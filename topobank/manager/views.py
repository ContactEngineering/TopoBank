import datetime
import logging
import os.path
import traceback
from io import BytesIO

import dateutil.parser
from bokeh.embed import components

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.db.models import Q
from django.http import HttpResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, UpdateView, CreateView, DeleteView, TemplateView, FormView
from django.views.generic.edit import FormMixin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.contrib import messages
from django.utils.text import slugify

from guardian.decorators import permission_required_or_403
from guardian.shortcuts import assign_perm, get_users_with_perms, remove_perm
from formtools.wizard.views import SessionWizardView
from notifications.signals import notify

from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from trackstats.models import Metric, Period

from SurfaceTopography.Support.UnitConversion import get_unit_conversion_factor

import topobank.taskapp.utils

from ..usage_stats.utils import increase_statistics_by_date, increase_statistics_by_date_and_object
from ..publication.models import MAX_LEN_AUTHORS_FIELD
from ..users.models import User

from .containers import write_surface_container
from .forms import TopographyFileUploadForm, TopographyMetaDataForm, TopographyWizardUnitsForm
from .forms import TopographyForm, SurfaceForm, SurfaceShareForm, SurfacePublishForm
from .models import Topography, Surface, TagModel, NewPublicationTooFastException, LoadTopographyException, \
    PlotTopographyException, PublicationException, topography_datafile_path
from .permissions import ObjectPermissions, ParentObjectPermissions, api_to_guardian
from .serializers import SurfaceSerializer, TopographySerializer, TagSearchSerizalizer, SurfaceSearchSerializer
from .utils import selected_instances, get_topography_reader, tags_for_user, get_reader_infos, \
    mailto_link_for_reporting_an_error, current_selection_as_basket_items, filtered_surfaces, \
    filtered_topographies, get_search_term, get_category, get_sharing_status, get_tree_mode, \
    subjects_to_base64, s3_post

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


#
# Using a wizard because we need intermediate calculations
#
# There are 3 forms, used in 3 steps (0,1, then 2):
#
# 0: loading of the topography file
# 1: choosing the data source, add measurement date and a description
# 2: adding physical size and units (for data which is not available in the file, for 1D or 2D)
#
# Maybe an alternative would be to use AJAX calls as described here (under "GET"):
#
#  https://sixfeetup.com/blog/making-your-django-templates-ajax-y
#
class TopographyCreateWizard(ORCIDUserRequiredMixin, SessionWizardView):
    form_list = [TopographyFileUploadForm, TopographyMetaDataForm, TopographyWizardUnitsForm]
    template_name = 'manager/topography_wizard.html'
    file_storage = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'topographies/wizard'))

    def get_form_initial(self, step):

        initial = {}

        if step in ['upload']:
            #
            # Pass surface in order to
            # - have it later in done() method (for upload)
            #
            # make sure that the surface exists and belongs to the current user
            try:
                surface = Surface.objects.get(id=int(self.kwargs['surface_id']))
            except Surface.DoesNotExist:
                raise PermissionDenied()
            if not self.request.user.has_perm('change_surface', surface):
                raise PermissionDenied()

            initial['surface'] = surface

        if step in ['metadata', 'units']:
            # provide datafile attribute from first step
            step0_data = self.get_cleaned_data_for_step('upload')
            datafile = step0_data['datafile']
            channel_infos = step0_data['channel_infos']

        if step == 'metadata':
            initial['name'] = os.path.basename(datafile.name)  # the original file name
            # Use the latest data available on all channels as initial measurement date, if any - see GH #433
            measurement_dates = []
            for ch in channel_infos:
                try:
                    measurement_time = ch.info[MEASUREMENT_TIME_INFO_FIELD]
                    if not isinstance(measurement_time, datetime.date):
                        try:
                            measurement_time = measurement_time.date()
                        except AttributeError:
                            measurement_time = dateutil.parser.parse(measurement_time).date()
                    measurement_dates.append(measurement_time)  # timezone is not known and not taken into account
                except KeyError:
                    # measurement time not available in channel
                    pass
                except ValueError as exc:
                    _log.info(f'Found measurement timestamp in file {datafile.name}, but could not parse: {exc}')

            initial['measurement_date'] = max(measurement_dates, default=None)

        if step in ['units']:

            step1_data = self.get_cleaned_data_for_step('metadata') or {'data_source': 0}
            # in case the form doesn't validate, the first data source is chosen, workaround for GH 691

            channel = int(step1_data['data_source'])
            channel_info = channel_infos[channel]

            #
            # Set initial size
            #

            has_2_dim = channel_info.dim == 2
            physical_sizes = channel_info.physical_sizes
            physical_sizes_is_None = (physical_sizes is None) or (physical_sizes == (None,)) \
                                     or (physical_sizes == (None, None))
            # workaround for GH 299 in PyCo and GH 446 in TopoBank

            if physical_sizes_is_None:
                initial_size_x, initial_size_y = None, None
                # both database fields are always set, also for 1D topographies
            elif has_2_dim:
                initial_size_x, initial_size_y = physical_sizes
            else:
                initial_size_x, = physical_sizes  # size is always a tuple
                initial_size_y = None  # needed for database field

            initial['size_x'] = initial_size_x
            initial['size_y'] = initial_size_y

            initial['size_editable'] = physical_sizes_is_None

            initial['is_periodic'] = False  # so far, this is not returned by the readers

            #
            # Set unit
            #
            initial['unit'] = channel_info.unit
            initial['unit_editable'] = initial['unit'] is None

            #
            # Set initial height scale factor
            #
            height_scale_factor_missing = channel_info.height_scale_factor is None  # missing in file
            initial['height_scale_editable'] = height_scale_factor_missing
            initial['height_scale'] = 1 if height_scale_factor_missing else channel_info.height_scale_factor

            #
            # Set initial undefined data; note that we do not know at this point if there is undefined data since
            # the file has never been read fully. We here only read headers; the file is only fully read in Celery
            # tasks. This is to limit memory usage of the main Django server.
            #
            initial['fill_undefined_data_mode'] = Topography.FILL_UNDEFINED_DATA_MODE_NOFILLING

            #
            # Set initial detrend mode
            #
            initial['detrend_mode'] = 'center'

            #
            # Set resolution (only for having the data later in the done method)
            #
            # TODO Can this be passed to done() differently? Creating the reader again later e.g.?
            #
            if has_2_dim:
                initial['resolution_x'], initial['resolution_y'] = channel_info.nb_grid_pts
            else:
                initial['resolution_x'], = channel_info.nb_grid_pts
                initial['resolution_y'] = None

        return initial

    def get_form_kwargs(self, step=None):

        kwargs = super().get_form_kwargs(step)

        if step in ['metadata', 'units']:
            # provide datafile attribute and reader from first step
            step0_data = self.get_cleaned_data_for_step('upload')
            channel_infos = step0_data['channel_infos']

        if step == 'metadata':

            def clean_channel_name(s):
                """Restrict data shown in the dropdown for the channel name.
                :param s: channel name as found in the file
                :return: string without NULL characters, 100 chars maximum
                """
                if s is None:
                    return "(unknown)"
                return s.strip('\0')[:100]

            #
            # Set data source choices based on file contents
            #
            kwargs['data_source_choices'] = [(k, clean_channel_name(channel_info.name)) for k, channel_info in
                                             enumerate(channel_infos)]

            #
            # Set surface in order to check for duplicate topography names
            #
            kwargs['surface'] = step0_data['surface']
            kwargs['autocomplete_tags'] = tags_for_user(self.request.user)

        if step in ['units']:
            step1_data = self.get_cleaned_data_for_step('metadata') or {'data_source': 0}
            # in case the form doesn't validate, the first data source is chosen, workaround for GH 691
            # TODO: why can this happen? handle differently?

            channel = int(step1_data['data_source'])
            channel_info = channel_infos[channel]

            has_2_dim = channel_info.dim == 2
            no_sizes_given = channel_info.physical_sizes is None

            # only allow periodic topographies in case of 2 dimension
            kwargs['allow_periodic'] = has_2_dim and no_sizes_given  # TODO simplify in 'no_sizes_given'?
            kwargs['has_size_y'] = has_2_dim  # TODO find common term, now we have 'has_size_y' and 'has_2_dim'
            kwargs['has_undefined_data'] = channel_info.has_undefined_data

        return kwargs

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form, **kwargs)
        surface = Surface.objects.get(id=int(self.kwargs['surface_id']))
        context['surface'] = surface

        redirect_in_get = self.request.GET.get("redirect")
        redirect_in_post = self.request.POST.get("redirect")

        if redirect_in_get:
            context.update({'cancel_action': redirect_in_get})
        elif redirect_in_post:
            context.update({'cancel_action': redirect_in_post})

        #
        # We want to display information about readers directly on upload page
        #
        if self.steps.current == "upload":
            context['reader_infos'] = get_reader_infos()

        #
        # Add context needed for tabs
        #
        context['extra_tabs'] = [
            {
                'title': f"{surface}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            },
            {
                'title': f"Add topography",
                'icon': "plus-square",
                'icon_style_prefix': 'far',
                'href': self.request.path,
                'active': True,
                'tooltip': f"Adding a topography to surface '{surface.label}'"
            }
        ]

        return context

    def done(self, form_list, **kwargs):
        """Finally use the form data when after finishing the wizard.

        :param form_list: list of forms
        :param kwargs:
        :return: HTTPResponse
        """
        #
        # collect all data from forms
        #
        d = dict((k, v) for form in form_list for k, v in form.cleaned_data.items())

        #
        # Check whether given surface can be altered by this user
        #
        surface = d['surface']
        if not self.request.user.has_perm('change_surface', surface):
            raise PermissionDenied()

        #
        # Set the topography's creator to the current user uploading the file
        #
        d['creator'] = self.request.user

        #
        # Remove helper data
        #
        del d['channel_infos']
        del d['resolution_value']
        del d['resolution_unit']
        del d['tip_radius_value']
        del d['tip_radius_unit']

        datafile = d['datafile']
        del d['datafile']

        #
        # create topography in database
        #
        instance = Topography(**d)
        instance.save()
        # we save once so the member variables like "data_source"
        # have the correct type for the next step, and we get an id
        # for constructing the file path

        #
        # move file to the permanent storage (wizard's files will be deleted)
        #
        new_path = topography_datafile_path(instance, os.path.basename(datafile.name))
        with datafile.open(mode='rb') as f:
            instance.datafile = default_storage.save(new_path, File(f))
        instance.save()

        #
        # Notify other others with access to the topography
        #
        topo = Topography.objects.get(id=instance.id)
        other_users = get_users_with_perms(topo.surface).filter(~Q(id=self.request.user.id))
        for u in other_users:
            notify.send(sender=self.request.user, verb='create', target=topo, recipient=u,
                        description=f"User '{self.request.user.name}' has created the topography '{topo.name}' " + \
                                    f"in surface '{topo.surface.name}'.",
                        href=reverse('manager:topography-detail', kwargs=dict(pk=topo.pk)))

        #
        # The topography could be correctly loaded and we show a page with details
        #
        return redirect('manager:topography-detail', pk=topo.pk)


class CorruptedTopographyView(TemplateView):
    template_name = "manager/topography_corrupted.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        surface = Surface.objects.get(id=kwargs['surface_id'])
        context['surface'] = surface
        #
        # Add context needed for tabs
        #
        context['extra_tabs'] = [
            {
                'title': f"{surface}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{surface.label}'"
            },
            {
                'title': f"Corrupted File",
                'icon': "flash",
                'href': self.request.path,
                'active': True,
                'tooltip': f"Failure while uploading a new file"
            }
        ]
        return context


class TopographyUpdateView(TopographyUpdatePermissionMixin, UpdateView):
    model = Topography
    form_class = TopographyForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        topo = self.object

        kwargs['has_size_y'] = topo.size_y is not None
        kwargs['autocomplete_tags'] = tags_for_user(self.request.user)

        toporeader = get_topography_reader(topo.datafile, format=topo.datafile_format)

        channel_info = toporeader.channels[topo.data_source]
        has_2_dim = channel_info.dim == 2
        no_sizes_given = channel_info.physical_sizes is None

        kwargs['allow_periodic'] = has_2_dim and no_sizes_given
        kwargs['has_undefined_data'] = topo.has_undefined_data
        return kwargs

    def form_valid(self, form):

        topo = self.object
        user = self.request.user
        notification_msg = f"User {user} changed topography '{topo.name}'. Changed fields: {','.join(form.changed_data)}."

        #
        # If a significant field changes, renew squeezed datafile, all analyses, and also thumbnail
        #
        # changed_dict = topo.tracker.changed()  # key: field name, value: previous field value
        changed_fields = form.changed_data

        _log.debug("These fields have been changed according to form: %s", changed_fields)

        significant_fields = {'size_x', 'size_y', 'unit', 'is_periodic', 'height_scale',
                              'fill_undefined_data_mode', 'detrend_mode', 'datafile', 'data_source',
                              'instrument_type',  # , 'instrument_parameters'
                              # 'tip_radius_value', 'tip_radius_unit',
                              }
        significant_fields_with_changes = set(changed_fields).intersection(significant_fields)

        instrument_fields = set(['instrument_type', 'instrument_parameters'])

        # check instrument_parameters manually, since this is not detected properly
        if form.cleaned_data['instrument_parameters'] != form.initial['instrument_parameters']:
            significant_fields_with_changes.add('instrument_parameters')
            _log.info("Instrument parameters changed:")
            _log.info("  before: %s", form.initial['instrument_parameters'])
            _log.info("  after:  %s", form.cleaned_data['instrument_parameters'])

        #
        # notify other users
        #
        other_users = get_users_with_perms(topo.surface).filter(~Q(id=user.id))
        for u in other_users:
            notify.send(sender=user, verb='change', target=topo,
                        recipient=u,
                        description=notification_msg,
                        href=reverse('manager:topography-detail', kwargs=dict(pk=topo.pk)))

        return super().form_valid(form)

    def get_success_url(self):
        if "save-stay" in self.request.POST:
            return reverse('manager:topography-update', kwargs=dict(pk=self.object.pk))
        else:
            return reverse('manager:topography-detail', kwargs=dict(pk=self.object.pk))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        topo = self.object
        try:
            context['topography_next'] = topo.get_next_by_measurement_date(surface=topo.surface).id
        except Topography.DoesNotExist:
            context['topography_next'] = topo.id
        try:
            context['topography_prev'] = topo.get_previous_by_measurement_date(surface=topo.surface).id
        except Topography.DoesNotExist:
            context['topography_prev'] = topo.id

        #
        # Add context needed for tabs
        #
        context['extra_tabs'] = [
            {
                'title': f"{topo.surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': f"{reverse('manager:surface-detail')}?surface={topo.surface.pk}",
                'active': False,
                'tooltip': f"Properties of surface '{topo.surface.label}'"
            },
            {
                'title': f"{topo.name}",
                'icon': "file",
                'icon_style_prefix': 'far',
                'href': reverse('manager:topography-detail', kwargs=dict(pk=topo.pk)),
                'active': False,
                'tooltip': f"Properties of topography '{topo.name}'"
            },
            {
                'title': f"Edit Topography",
                'icon': "pencil",
                'href': self.request.path,
                'active': True,
                'tooltip': f"Editing topography '{topo.name}'"
            }
        ]

        return context


def topography_plot(request, pk):
    """Render an HTML snippet with topography plot"""
    try:
        pk = int(pk)
        topo = Topography.objects.get(pk=pk)
        assert request.user.has_perm('view_surface', topo.surface)
    except (ValueError, Topography.DoesNotExist, AssertionError):
        raise PermissionDenied()  # This should be shown independent of whether the surface exists

    errors = []  # list of dicts with keys 'message' and 'link'
    context = {}

    plotted = False

    try:
        plot = topo.get_plot()
        plotted = True
    except LoadTopographyException as exc:
        err_message = "Topography '{}' (id: {}) cannot be loaded unexpectedly.".format(
            topo.name, topo.id)
        _log.error(err_message)
        link = mailto_link_for_reporting_an_error(f"Failure loading topography (id: {topo.id})",
                                                  "Plotting measurement",
                                                  err_message,
                                                  traceback.format_exc())

        errors.append(dict(message=err_message, link=link))
    except PlotTopographyException as exc:
        err_message = "Topography '{}' (id: {}) cannot be plotted.".format(topo.name, topo.id)
        _log.error(err_message)
        link = mailto_link_for_reporting_an_error(f"Failure plotting measurement (id: {topo.id})",
                                                  "Plotting measurement",
                                                  err_message,
                                                  traceback.format_exc())

        errors.append(dict(message=err_message, link=link))

    if plotted:
        script, div = components(plot)
        context['image_plot_script'] = script
        context['image_plot_div'] = div

    context['errors'] = errors

    return render(request, 'manager/topography_plot.html', context=context)


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


def thumbnail(request, pk):
    """Returns image data for a topography thumbail

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

    image = topo.thumbnail
    response = HttpResponse(content_type="image/png")
    try:
        response.write(image.file.read())
    except Exception as exc:
        _log.warning(f"Cannot load thumbnail for topography {topo.id}. Reason: {exc}")
        # return some default image so the client gets sth in any case
        with staticfiles_storage.open('images/thumbnail_unavailable.png', mode='rb') as img_file:
            response.write(img_file.read())

    return response


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
