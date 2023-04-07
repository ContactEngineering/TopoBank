import json

import itertools
from collections import OrderedDict

from django.contrib.contenttypes.models import ContentType
from django.http import Http404, JsonResponse
from django.views.generic import DetailView, FormView
from django.urls import reverse_lazy
from django.core.files.storage import default_storage
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, reverse
from django.conf import settings

from rest_framework import mixins, viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

import bokeh.palettes as palettes

from pint import UnitRegistry, UndefinedUnitError

from trackstats.models import Metric

from ..manager.models import Topography, Surface, SurfaceCollection
from ..manager.utils import instances_to_selection, selection_to_subjects_dict, subjects_from_dict
from ..usage_stats.utils import increase_statistics_by_date_and_object
from .forms import FunctionSelectForm
from .models import Analysis, AnalysisFunction, AnalysisCollection
from .serializers import AnalysisSerializer
from .utils import AnalysisController, request_analysis, renew_analysis, filter_and_order_analyses, \
    palette_for_topographies
from .registry import AnalysisRegistry

import logging

_log = logging.getLogger(__name__)

SMALLEST_ABSOLUT_NUMBER_IN_LOGPLOTS = 1e-100
MAX_NUM_POINTS_FOR_SYMBOLS = 50
LINEWIDTH_FOR_SURFACE_AVERAGE = 4


class AnalysisView(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    """Retrieve status of analysis (GET) and renew analysis (POST)"""
    queryset = Analysis.objects.all()
    serializer_class = AnalysisSerializer

    def update(self, request, *args, **kwargs):
        """Renew existing analysis."""
        analysis = self.get_object()
        if analysis.is_visible_for_user(request.user):
            new_analysis = renew_analysis(analysis)
            serializer = self.get_serializer(new_analysis)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response({}, status=status.HTTP_403_FORBIDDEN)


@api_view(['POST'])
def generic_card_view(request):
    """Gets function ids and subject ids from POST parameters.

    :return: dict to be used in analysis card templates' context

    The returned dict has the following keys:

      title: card title
      function: AnalysisFunction instance
      unique_kwargs: dict with common kwargs for all analyses, None if not unique
      analyses_available: list of all analyses which are relevant for this view
      analyses_success: list of successfully finished analyses (result is useable, can be displayed)
      analyses_failure: list of analyses finished with failures (result has traceback, can't be displayed)
      analyses_unready: list of analyses which are still running or pending
      subjects_missing: list of subjects for which there is no Analysis object yet
      subjects_requested_json: json representation of list with all requested subjects as 2-tuple
                               (subject_type.id, subject.id)
    """
    user = request.user
    data = request.data

    function_id = int(data.get('function_id'))
    subjects = data.get('subjects')

    filter = AnalysisController(user, subjects, function_id=function_id)

    #
    # for statistics, count views per function
    #
    increase_statistics_by_date_and_object(Metric.objects.ANALYSES_RESULTS_VIEW_COUNT, obj=filter.function)

    #
    # comprise context for analysis result card
    #
    return Response({
        'title': filter.function.name,
        'function_id': filter.function.id,
        'unique_kwargs': filter.unique_kwargs,
        'analyses_available': filter(),  # all Analysis objects related to this card
        'analyses_success': filter(['su'], True),  # ..the ones which were successful and can be displayed
        'analyses_failure': filter(['fa'], True),  # ..the ones which have failures and can't be displayed
        'analyses_unready': filter(['su', 'fa'], False),  # ..the ones which are still running
        'subjects_missing': filter.subjects_without_analysis_results,
        # subjects for which there is no Analysis object yet
        'subjects': filter.subjects_dict,  # can be used to re-trigger analyses
        'extra_warnings': [],  # use list of dicts of form {'alert_class': 'alert-info', 'message': 'your message'},
        'analyses_renew_url': reverse('analysis:renew'),
        'dois': filter.dois
    })


@api_view(['POST'])
def series_card_view(request):
    user = request.user
    data = request.data

    if not 'function_id' in data:
        raise Http404("Missing parameter `function_id`")
    if not 'subjects' in data:
        raise Http404("Missing parameter `subjects")

    function_id = int(data.get('function_id'))
    subjects = data.get('subjects')

    controller = AnalysisController(user, subjects, function_id=function_id)

    #
    # for statistics, count views per function
    #
    increase_statistics_by_date_and_object(Metric.objects.ANALYSES_RESULTS_VIEW_COUNT, obj=controller.function)

    #
    # Trigger missing analyses
    #
    controller.trigger_missing_analyses()

    #
    # Filter only successful ones
    #
    analyses_success = controller(['su'], True)

    #
    # order analyses such that surface analyses are coming last (plotted on top)
    analyses_success_list = filter_and_order_analyses(analyses_success)
    data_sources_dict = []

    # Special case: It can happen that there is one surface with a successful analysis
    # but the only measurement's analysis has no success. In this case there is also
    # no successful analysis to display because the surface has only one measurement.

    context = {
        'dois': controller.dois,
        'extraWarnings': [],
        'analyses': controller.to_representation(request=request)
    }

    plot_configuration = {
        'title': controller.function.name
    }

    nb_analyses_success = len(analyses_success_list)
    if nb_analyses_success == 0:
        #
        # Prepare plot, controls, and table with special values..
        #
        plot_configuration['dataSources'] = []
        plot_configuration['categories'] = [
            {
                'title': "Averages / Measurements",
                'key': "subjectName",
            },
            {
                'title': "Data Series",
                'key': "seriesName",
            },
        ]
        context['plotConfiguration'] = plot_configuration
        return Response(context)

    #
    # Extract subject names for display
    #
    surface_ct = ContentType.objects.get_for_model(Surface)
    surfacecollection_ct = ContentType.objects.get_for_model(SurfaceCollection)
    topography_ct = ContentType.objects.get_for_model(Topography)

    subject_names = []  # will be shown under category with key "subject_name" (see plot.js)
    has_at_least_one_surface_subject = False
    has_at_least_one_surfacecollection_subject = False
    for a in analyses_success_list:
        s = a.subject
        subject_ct = s.get_content_type()
        subject_name = s.label.replace("'", "&apos;")
        if subject_ct == surface_ct:
            subject_name = f"Average of »{subject_name}«"
            has_at_least_one_surface_subject = True
        if subject_ct == surfacecollection_ct:
            has_at_least_one_surfacecollection_subject = True
        subject_names.append(subject_name)

    #
    # Use first analysis to determine some properties for the whole plot
    #
    first_analysis_result = analyses_success_list[0].result
    xunit = first_analysis_result['xunit'] if 'xunit' in first_analysis_result else None
    yunit = first_analysis_result['yunit'] if 'yunit' in first_analysis_result else None

    ureg = UnitRegistry()  # for unit conversion for each analysis individually, see below

    #
    # Determine axes labels
    #
    x_axis_label = first_analysis_result['xlabel']
    if xunit is not None:
        x_axis_label += f' ({xunit})'
    y_axis_label = first_analysis_result['ylabel']
    if yunit is not None:
        y_axis_label += f' ({yunit})'

    #
    # Context information for the figure
    #
    def _get_axis_type(key):
        return first_analysis_result.get(key) or "linear"

    plot_configuration.update({
        'xAxisLabel': x_axis_label,
        'yAxisLabel': y_axis_label,
        'xAxisType': _get_axis_type('xscale'),
        'yAxisType': _get_axis_type('yscale'),
        'outputBackend': settings.BOKEH_OUTPUT_BACKEND
    })

    #
    # First traversal: find all available series names and sort them
    #
    # Also collect number of topographies and surfaces
    #
    series_names = set()
    nb_surfaces = 0  # Total number of averages/surfaces shown
    nb_surfacecollections = 0  # Total number of surface collections shown
    nb_topographies = 0  # Total number of topography results shown
    nb_others = 0  # Total number of results for other kinds of subject types

    for analysis in analyses_success_list:
        #
        # handle task state
        #
        if analysis.task_state != analysis.SUCCESS:
            continue  # should not happen if only called with successful analyses

        series_names.update([s['name'] if 'name' in s else f'{i}'
                             for i, s in enumerate(analysis.result_metadata['series'])])

        if isinstance(analysis.subject, Surface):
            nb_surfaces += 1
        elif isinstance(analysis.subject, Topography):
            nb_topographies += 1
        elif isinstance(analysis.subject, SurfaceCollection):
            nb_surfacecollections += 1
        else:
            nb_others += 1

    series_names = sorted(list(series_names))  # index of a name in this list is the "series_name_index"
    visible_series_indices = set()  # elements: series indices, decides whether a series is visible

    #
    # Prepare helpers for dashes and colors
    #
    surface_color_palette = palettes.Greys256  # surfaces are shown in black/grey
    topography_color_palette = palette_for_topographies(nb_topographies)

    dash_cycle = itertools.cycle(['solid', 'dashed', 'dotted', 'dotdash', 'dashdot'])

    subject_colors = OrderedDict()  # key: subject instance, value: color

    series_dashes = OrderedDict()  # key: series name

    DEFAULT_ALPHA_FOR_TOPOGRAPHIES = 0.3 if has_at_least_one_surface_subject else 1.0

    #
    # Second traversal: Prepare metadata for plotting
    #
    # The plotting is done in Javascript on client side.
    # The metadata is prepared here, the data itself will be retrieved
    # by an AJAX request. The url for this request is also prepared here.
    #
    surface_index = -1
    topography_index = -1
    for analysis_idx, analysis in enumerate(analyses_success_list):
        #
        # Define some helper variables
        #
        subject = analysis.subject

        is_surface_analysis = isinstance(subject, Surface)
        is_topography_analysis = isinstance(subject, Topography)
        # is_surfacecollection_analysis = isinstance(subject, SurfaceCollection)

        #
        # Change display name depending on whether there is a parent analysis or not
        #
        parent_analysis = None
        if is_topography_analysis and analysis.subject.surface.num_topographies() > 1:
            for a in analyses_success_list:
                if a.subject_type == surface_ct and a.subject_id == analysis.subject.surface.id and \
                    a.function == analysis.function:
                    parent_analysis = a

        subject_display_name = subject_names[analysis_idx]

        #
        # Decide for colors
        #
        if is_surface_analysis:
            # Surface results are plotted in black/grey
            surface_index += 1
            subject_colors[subject] = \
                surface_color_palette[surface_index * len(surface_color_palette) // nb_surfaces]
        elif is_topography_analysis:
            topography_index += 1
            subject_colors[subject] = topography_color_palette[topography_index]
        else:
            subject_colors[subject] = 'black'  # Find better colors later, if needed

        #
        # Handle unexpected task states for robustness, shouldn't be needed in general
        #
        if analysis.task_state != analysis.SUCCESS:
            # not ready yet
            continue  # should not happen if only called with successful analyses

        #
        # Find out scale for data
        #
        result_metadata = analysis.result_metadata
        series_metadata = result_metadata['series']

        extra_warnings = []

        if xunit is None:
            analysis_xscale = 1
        else:
            try:
                analysis_xscale = ureg.convert(1, result_metadata['xunit'], xunit)
            except UndefinedUnitError as exc:
                err_msg = f"Cannot convert x units when displaying results for analysis with id {analysis.id}. " \
                          f"Cause: {exc}"
                _log.error(err_msg)
                extra_warnings.append(
                    dict(alert_class='alert-warning',
                         message=err_msg)
                )
                continue
        if yunit is None:
            analysis_yscale = 1
        else:
            try:
                analysis_yscale = ureg.convert(1, result_metadata['yunit'], yunit)
            except UndefinedUnitError as exc:
                err_msg = f"Cannot convert y units when displaying results for analysis with id {analysis.id}. " \
                          f"Cause: {exc}"
                _log.error(err_msg)
                extra_warnings.append(
                    dict(alert_class='alert-warning',
                         message=err_msg)
                )
                continue

        for series_idx, s in enumerate(series_metadata):
            #
            # Collect data for visibility of the corresponding series
            #
            series_url = reverse('analysis:data', args=(analysis.pk, f'series-{series_idx}.json'))
            # series_url = default_storage.url(f'{analysis.storage_prefix}/series-{series_idx}.json')

            series_name = s['name'] if 'name' in s else f'{series_idx}'
            series_name_idx = series_names.index(series_name)

            is_visible = s['visible'] if 'visible' in s else True
            if is_visible:
                visible_series_indices.add(series_name_idx)
                # as soon as one dataset wants this series to be visible,
                # this series will be visible for all

            #
            # Find out dashes for data series
            #
            if series_name not in series_dashes:
                series_dashes[series_name] = next(dash_cycle)
                # series_symbols[series_name] = next(symbol_cycle)

            #
            # Actually plot the line
            #
            show_symbols = s['nbDataPoints'] <= MAX_NUM_POINTS_FOR_SYMBOLS if 'nbDataPoints' in s else True

            curr_color = subject_colors[subject]
            curr_dash = series_dashes[series_name]

            # hover_name = "{} for '{}'".format(series_name, topography_name)
            line_width = LINEWIDTH_FOR_SURFACE_AVERAGE if is_surface_analysis else 1
            alpha = DEFAULT_ALPHA_FOR_TOPOGRAPHIES if is_topography_analysis else 1.

            #
            # Find out whether this dataset for this special series has a parent dataset
            # in the parent_analysis, which means whether the same series is available there
            #
            has_parent = (parent_analysis is not None) and \
                         any(s['name'] == series_name if 'name' in s else f'{i}' == series_name
                             for i, s in enumerate(parent_analysis.result_metadata['series']))

            #
            # Context information for this data source, will be interpreted by client JS code
            #
            data_sources_dict += [{
                'sourceName': f'analysis-{analysis.id}',
                'subjectName': subject_display_name,
                'subjectNameIndex': analysis_idx,
                'subjectNameHasParent': parent_analysis is not None,
                'seriesName': series_name,
                'seriesNameIndex': series_name_idx,
                'hasParent': has_parent,  # can be used for the legend
                'xScaleFactor': analysis_xscale,
                'yScaleFactor': analysis_yscale,
                'url': series_url,
                'color': curr_color,
                'dash': curr_dash,
                'width': line_width,
                'alpha': alpha,
                'showSymbols': show_symbols,
                'visible': series_name_idx in visible_series_indices,  # independent of subject
                'isSurfaceAnalysis': is_surface_analysis,
                'isTopographyAnalysis': is_topography_analysis
            }]

    plot_configuration['dataSources'] = data_sources_dict
    plot_configuration['categories'] = [
        {
            'title': "Averages / Measurements",
            'key': "subjectName",
        },
        {
            'title': "Data series",
            'key': "seriesName",
        },
    ]

    context['plotConfiguration'] = plot_configuration
    context['extraWarnings'] = extra_warnings

    return Response(context)


@api_view(['POST'])
def submit_analyses_view(request):
    """Requests analyses.
    :param request:
    :return: HTTPResponse
    """
    user = request.user
    data = request.data

    if user.is_anonymous:
        raise PermissionDenied()

    function_id = int(data.get('function_id'))
    subjects = data.get('subjects')
    function_kwargs = data.get('function_kwargs')

    controller = AnalysisController(user, subjects, function_id=function_id, function_kwargs=function_kwargs)

    #
    # Trigger missing analyses
    #
    controller.trigger_missing_analyses()

    # allowed = True
    # for subject in subjects:
    #    allowed &= subject.is_shared(user)
    #    if not allowed:
    #        break

    return Response({
        'analyses': controller.to_representation(request=request)
    }, status=200)


def data(request, pk, location):
    """Request data stored for a particular analysis.

    Before redirecting to the data, the permissions
    of the current user are checked for the given analysis.
    The user needs permissions for the data as well as
    the analysis function performed should be available.

    Parameters
    ----------

    pk: int
        id of Analysis instance
    location: str
        path underneath given analysis where file can be found

    Returns
    -------
    Redirects to file on storage.
    """
    try:
        pk = int(pk)
    except ValueError:
        raise Http404()

    analysis = Analysis.objects.get(id=pk)

    if not analysis.is_visible_for_user(request.user):
        raise PermissionDenied()

    # okay, we have a valid analysis and the user is allowed to see it

    name = f'{analysis.storage_prefix}/{location}'
    url = default_storage.url(name)
    return redirect(url)


def extra_tabs_if_single_item_selected(topographies, surfaces):
    """Return contribution to context for opening extra tabs if a single topography/surface is selected.

    Parameters
    ----------
    topographies: list of topographies
        Use here the result of function `utils.selected_instances`.

    surfaces: list of surfaces
        Use here the result of function `utils.selected_instances`.

    Returns
    -------
    Sequence of dicts, each dict corresponds to an extra tab.

    """
    tabs = []

    if len(topographies) == 1 and len(surfaces) == 0:
        # exactly one topography was selected -> show also tabs of topography
        topo = topographies[0]
        tabs.extend([
            {
                'title': f"{topo.surface.label}",
                'icon': "gem",
                'icon_style_prefix': 'far',
                'href': reverse('manager:surface-detail', kwargs=dict(pk=topo.surface.pk)),
                'active': False,
                'login_required': False,
                'tooltip': f"Properties of surface '{topo.surface.label}'",
            },
            {
                'title': f"{topo.name}",
                'icon': "file",
                'icon_style_prefix': 'far',
                'href': reverse('manager:topography-detail', kwargs=dict(pk=topo.pk)),
                'active': False,
                'login_required': False,
                'tooltip': f"Properties of measurement '{topo.name}'",
            }
        ])
    elif len(surfaces) == 1 and all(t.surface == surfaces[0] for t in topographies):
        # exactly one surface was selected -> show also tab of surface
        surface = surfaces[0]
        tabs.append(
            {
                'title': f"{surface.label}",
                'icon': 'gem',
                'icon_style_prefix': 'far',
                'href': reverse('manager:surface-detail', kwargs=dict(pk=surface.pk)),
                'active': False,
                'login_required': False,
                'tooltip': f"Properties of surface '{surface.label}'",
            }
        )
    return tabs


class AnalysisFunctionDetailView(DetailView):
    """Show analyses for a given analysis function.
    """
    model = AnalysisFunction
    template_name = "analysis/analyses_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        function = self.object
        # Check if user is allowed to use this function
        reg = AnalysisRegistry()
        if function.name not in reg.get_analysis_function_names(self.request.user):
            raise PermissionDenied()

        # filter subjects to those this user is allowed to see
        effective_topographies, effective_surfaces, subjects = selection_to_subjects_dict(self.request)

        # get analysis result type
        visualization_app_name, visualization_type = reg.get_visualization_type_for_function_name(function.name)
        api_name = f'{visualization_app_name}:card-{visualization_type}'
        card = dict(
            visualization_type=visualization_type,
            api_url=reverse(api_name),
            function=function,
            subjects=subjects)

        context['card'] = card

        # Decide whether to open extra tabs for surface/topography details
        tabs = extra_tabs_if_single_item_selected(effective_topographies, effective_surfaces)
        tabs.extend([
            {
                'title': f"Analyze",
                'icon': "chart-area",
                'href': reverse('analysis:list'),
                'active': False,
                'login_required': False,
                'tooltip': "Results for selected analysis functions",
            },
            {
                'title': f"{function.name}",
                'icon': "chart-area",
                'href': self.request.path,
                'active': True,
                'login_required': False,
                'tooltip': f"Results for analysis '{function.name}'",
                'show_basket': True,
            }
        ])
        context['extra_tabs'] = tabs

        return context


class AnalysesListView(FormView):
    """View showing analyses from multiple functions.
    """
    form_class = FunctionSelectForm
    success_url = reverse_lazy('analysis:list')
    template_name = "analysis/analyses_list.html"

    def get_initial(self):

        user = self.request.user

        if 'collection_id' in self.kwargs:
            analysis_collection_id = self.kwargs['collection_id']
            try:
                analysis_collection = AnalysisCollection.objects.get(id=analysis_collection_id)
            except AnalysisCollection.DoesNotExist:
                raise Http404("Collection does not exist")

            if analysis_collection.owner != user:
                raise PermissionDenied()

            functions = set(a.function for a in analysis_collection.analyses.all())
            surfaces = set(a.subject for a in analysis_collection.analyses.all() if a.is_surface_related)
            topographies = set(a.subject for a in analysis_collection.analyses.all() if a.is_topography_related)

            # as long as we have the current UI (before implementing GH #304)
            # we also set the collection's function and topographies as selection
            selection = instances_to_selection(topographies=topographies, surfaces=surfaces)
            self.request.session['selection'] = tuple(selection)
            self.request.session['selected_functions'] = tuple(f.id for f in functions)

        elif 'surface_id' in self.kwargs:
            surface_id = self.kwargs['surface_id']
            try:
                surface = Surface.objects.get(id=surface_id)
            except Surface.DoesNotExist:
                raise PermissionDenied()

            if not user.has_perm('view_surface', surface):
                raise PermissionDenied()

            #
            # So we have an existing surface and are allowed to view it, so we select it
            #
            self.request.session['selection'] = ['surface-{}'.format(surface_id)]

        elif 'topography_id' in self.kwargs:
            topo_id = self.kwargs['topography_id']
            try:
                topo = Topography.objects.get(id=topo_id)
            except Topography.DoesNotExist:
                raise PermissionDenied()

            if not user.has_perm('view_surface', topo.surface):
                raise PermissionDenied()

            #
            # So we have an existing topography and are allowed to view it, so we select it
            #
            self.request.session['selection'] = ['topography-{}'.format(topo_id)]

        return dict(
            functions=AnalysesListView._selected_functions(self.request),
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        functions = form.cleaned_data.get('functions', [])
        self.request.session['selected_functions'] = list(t.id for t in functions)
        return super().form_valid(form)

    @staticmethod
    def _selected_functions(request):
        """Returns selected functions as saved in session or, if given, in POST parameters.

        Functions are ordered by name.
        """
        function_ids = request.session.get('selected_functions', [])
        functions = AnalysisFunction.objects.filter(id__in=function_ids).order_by('name')

        # filter function by those which have available implementations for the given user
        return functions.filter(name__in=AnalysisRegistry().get_analysis_function_names(request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        selected_functions = self._selected_functions(self.request)

        effective_topographies, effective_surfaces, subjects = selection_to_subjects_dict(self.request)

        # for displaying result card, we need a dict for each card,
        # which then can be used to load the result data in the background
        cards = []
        reg = AnalysisRegistry()
        for function in selected_functions:
            visualization_app_name, visualization_type = reg.get_visualization_type_for_function_name(function.name)
            api_name = f'{visualization_app_name}:card-{visualization_type}'
            cards.append(dict(id=f"card-{function.pk}",
                              function=function,
                              visualization_type=visualization_type,
                              api_url=reverse(api_name),
                              subjects=subjects))

        context['cards'] = cards

        # Decide whether to open extra tabs for surface/topography details
        tabs = extra_tabs_if_single_item_selected(effective_topographies, effective_surfaces)
        tabs.append(
            {
                'title': f"Analyze",
                'icon': "chart-area",
                'icon-style-prefix': 'fas',
                'href': self.request.path,
                'active': True,
                'login_required': False,
                'tooltip': "Results for selected analysis functions",
                'show_basket': True,
            }
        )
        context['extra_tabs'] = tabs

        return context
