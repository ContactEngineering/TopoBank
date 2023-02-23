import pickle
import json
from typing import Optional, Dict, Any

import itertools
from collections import OrderedDict

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, Http404, JsonResponse
from django.views.generic import DetailView, FormView, TemplateView
from django.urls import reverse_lazy
from django import template
from django.core.files.storage import default_storage
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, reverse
from django.conf import settings

from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

import bokeh.palettes as palettes

from pint import UnitRegistry, UndefinedUnitError

from trackstats.models import Metric

from ..manager.models import Topography, Surface, SurfaceCollection
from ..manager.utils import instances_to_selection, selection_to_subjects_dict, subjects_from_dict, subjects_to_dict
from ..usage_stats.utils import increase_statistics_by_date_and_object
from .models import Analysis, AnalysisFunction, AnalysisCollection
from .forms import FunctionSelectForm
from .utils import get_latest_analyses, request_analysis, renew_analysis, filter_and_order_analyses, \
    palette_for_topographies
from .registry import AnalysisRegistry, register_card_view_class
from .functions import ART_SERIES

import logging

_log = logging.getLogger(__name__)

SMALLEST_ABSOLUT_NUMBER_IN_LOGPLOTS = 1e-100
MAX_NUM_POINTS_FOR_SYMBOLS = 50
LINEWIDTH_FOR_SURFACE_AVERAGE = 4


def switch_card_view(request):
    """Selects appropriate card view upon request.

    Within the request, there is hint to which function
    the request is related to. Depending on the function,
    another view should be used.

    This view here creates than a new view and let
    it return the response instead.

    The request must have a "function_id" in its
    POST parameters.

    :param request:
    :return: HTTPResponse
    """
    if not request.is_ajax():
        return Http404

    try:
        function_id = int(request.POST.get('function_id'))
    except (KeyError, ValueError, TypeError):
        return HttpResponse("Error in POST arguments")

    function = AnalysisFunction.objects.get(id=function_id)

    reg = AnalysisRegistry()
    view_class = reg.get_card_view_class(reg.get_analysis_result_type_for_function_name(function.name))

    #
    # for statistics, count views per function
    #
    metric = Metric.objects.ANALYSES_RESULTS_VIEW_COUNT
    increase_statistics_by_date_and_object(metric, obj=function)

    return view_class.as_view()(request)


def _subject_colors(analyses):
    """Return dict with mapping from subject to color for plotting.

    Parameters
    ----------
    analyses

    Returns
    -------
    dict with key: subject, value: color string suitable or bokeh
    """
    pass


@register_card_view_class('generic')
class SimpleCardView(TemplateView):
    """Very basic display of results. Base class for more complex views.

    Must be used in an AJAX call.
    """

    template_name_pattern = "analysis/simple_card_{template_flavor}.html"

    def _template_name(self, template_flavor, pat=None):
        """Build template name.

        Parameters
        ----------
        template_flavor: str
            Template flavor, e.g. 'list' and 'detail'.
        """
        if pat is None:
            pat = self.template_name_pattern

        return pat.format(template_flavor=template_flavor)

    def get_template_names(self):
        """Return list of possible templates.

        Uses request parameter 'template_flavor'.
        """
        try:
            template_flavor = self.request.POST.get('template_flavor')
        except (KeyError, ValueError):
            raise ValueError("Cannot read 'template_flavor' from POST arguments.")

        if template_flavor is None:
            raise ValueError("Missing 'template_flavor' in POST arguments.")

        template_name = self._template_name(template_flavor)

        #
        # If template does not exist, return SimpleCardView template
        #
        try:
            template.loader.get_template(template_name)
        except template.TemplateDoesNotExist:
            _log.warning(f"Template '{template_name}' not found. Falling back to simple card template.")
            template_name = self._template_name(template_flavor, SimpleCardView.template_name_pattern)

        return [template_name]

    def get_context_data(self, **kwargs):
        """Gets function ids and subject ids from POST parameters.

        :return: dict to be used in analysis card templates' context

        The returned dict has the following keys:

          card_id: A CSS id referencing the card which is to be delivered
          title: card title
          function: AnalysisFunction instance
          unique_kwargs: dict with common kwargs for all analyses, None if not unique
          analyses_available: list of all analyses which are relevant for this view
          analyses_success: list of successfully finished analyses (result is useable, can be displayed)
          analyses_failure: list of analyses finished with failures (result has traceback, can't be displayed)
          analyses_unready: list of analyses which are still running
          subjects_missing: list of subjects for which there is no Analysis object yet
          subjects_requested_json: json representation of list with all requested subjects as 2-tuple
                                   (subject_type.id, subject.id)
        """
        context = super().get_context_data(**kwargs)

        request = self.request
        request_method = request.POST
        user = request.user

        try:
            function_id = int(request_method.get('function_id'))
            card_id = request_method.get('card_id')
            subjects = request_method.get('subjects')
        except Exception as exc:
            _log.error("Cannot decode POST arguments from analysis card request. Details: %s", exc)
            raise

        function = AnalysisFunction.objects.get(id=function_id)

        # Calculate subjects for the analyses, filtered for those which have an implementation
        subjects_requested = subjects_from_dict(subjects, function=function)

        # The following is needed for re-triggering analyses, now filtered
        # in order to trigger only for subjects which have an implementation
        subjects = subjects_to_dict(subjects_requested)

        #
        # Find the latest analyses for which the user has read permission for the related data
        #
        analyses_available = get_latest_analyses(user, function, subjects_requested)

        #
        # collect list of subjects for which an analysis instance is missing
        #
        subjects_available = [a.subject for a in analyses_available]
        subjects_missing = [s for s in subjects_requested if s not in subjects_available]

        #
        # collect all keyword arguments and check whether they are equal
        #
        unique_kwargs: Dict[ContentType, Optional[Any]] = {}  # key: ContentType, value: dict or None
        # - if a contenttype is missing as key, this means:
        #   There are no analyses available for this contenttype
        # - if a contenttype exists, but value is None, this means:
        #   There arguments of the analyses for this contenttype are not unique

        for analysis in analyses_available:
            kwargs = pickle.loads(analysis.kwargs)

            if analysis.subject_type not in unique_kwargs:
                unique_kwargs[analysis.subject_type] = kwargs
            elif unique_kwargs[analysis.subject_type] is not None:  # was unique so far
                if kwargs != unique_kwargs[analysis.subject_type]:
                    unique_kwargs[analysis.subject_type] = None
                    # Found differing arguments for this subject_type
                    # We need to continue in the loop, because of the other subject types

        #
        # automatically trigger analyses for missing subjects (topographies or surfaces)
        #
        # Save keyword arguments which should be used for missing analyses,
        # sorted by subject type
        kwargs_for_missing = {}
        for st in function.get_implementation_types():
            try:
                kw = unique_kwargs[st]
                if kw is None:
                    kw = {}
            except KeyError:
                kw = function.get_default_kwargs(st)
            kwargs_for_missing[st] = kw

        # For every possible implemented subject type the following is done:
        # We use the common unique keyword arguments if there are any; if not
        # the default arguments for the implementation is used

        subjects_triggered = []
        for subject in subjects_missing:
            if subject.is_shared(user):
                ct = ContentType.objects.get_for_model(subject)
                analysis_kwargs = kwargs_for_missing[ct]
                triggered_analysis = request_analysis(user, function, subject, **analysis_kwargs)
                subjects_triggered.append(subject)
                # topographies_available_ids.append(topo.id)
                _log.info(f"Triggered analysis {triggered_analysis.id} for function '{function.name}' "
                          f"and subject '{subject}'.")
        subjects_missing = [s for s in subjects_missing if s not in subjects_triggered]

        # now all subjects which needed to be triggered, should have been triggered
        # with common arguments if possible
        # collect information about available analyses again
        if len(subjects_triggered) > 0:

            # if no analyses where available before, unique_kwargs is None
            # which is interpreted as "differing arguments". This is wrong
            # in that case
            if len(analyses_available) == 0:
                unique_kwargs = kwargs_for_missing

            analyses_available = get_latest_analyses(user, function, subjects_requested)

        #
        # Turn available analyses into a list
        #
        analyses_available = list(analyses_available)

        #
        # Determine status code of request - do we need to trigger request again?
        #
        analyses_ready = [a for a in analyses_available
                          if a.task_state in ['su', 'fa']]
        # Leave out those analyses which have a state meaning "ready", but
        # have no result file:
        ids_of_ready_analyses_with_result_file = [a.id for a in analyses_ready
                                                  if a.has_result_file]
        ready_analyses_without_result_file = [a for a in analyses_ready
                                              if a.id not in ids_of_ready_analyses_with_result_file]
        analyses_ready = [a for a in analyses_ready
                          if a.id in ids_of_ready_analyses_with_result_file]
        analyses_unready = [a for a in analyses_available
                            if a.id not in ids_of_ready_analyses_with_result_file]

        #
        # Those analyses, which seem to be ready but have no result, should be re-triggered
        # and added to the unready results
        #
        if len(ready_analyses_without_result_file) > 0:
            _log.info(f"There are {len(ready_analyses_without_result_file)} analyses marked as ready but "
                      "without result file. These will be retriggered.")
        additional_unready_analyses = [renew_analysis(a) for a in ready_analyses_without_result_file]
        analyses_unready += additional_unready_analyses

        #
        # collect lists of successful analyses and analyses with failures
        #
        # Only the successful ones should show up in the plot
        # the ones with failure should be shown elsewhere
        analyses_success = [analysis for analysis in analyses_ready if analysis.task_state == 'su']
        analyses_failure = [analysis for analysis in analyses_ready if analysis.task_state == 'fa']

        #
        # Collect dois from all available analyses
        #
        dois = sorted(set().union(*[a.dois for a in analyses_available]))

        #
        # comprise context for analysis result card
        #
        context.update(dict(
            card_id=card_id,
            title=function.name,
            function=function,
            unique_kwargs=unique_kwargs,
            analyses_available=analyses_available,  # all Analysis objects related to this card
            analyses_success=analyses_success,  # ..the ones which were successful and can be displayed
            analyses_failure=analyses_failure,  # ..the ones which have failures and can't be displayed
            analyses_unready=analyses_unready,  # ..the ones which are still running
            subjects_missing=subjects_missing,  # subjects for which there is no Analysis object yet
            subjects=subjects,  # can be used to re-trigger analyses
            extra_warnings=[],  # use list of dicts of form {'alert_class': 'alert-info', 'message': 'your message'},
            analyses_renew_url=reverse('analysis:renew'),
            dois=dois,
        ))

        return context

    def post(self, request, *args, **kwargs):
        """
        Returns status code

        - 200 if all analysis are finished (success or failure).
        - 202 if there are still analyses which not have been finished,
          this can be used to request the card again later

        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        response = super().get(request, *args, **kwargs)

        #
        # Set status code depending on whether all analyses are finished
        #
        context = response.context_data
        num_analyses_avail = len(context['analyses_available'])
        num_analyses_ready = len(context['analyses_success']) + len(context['analyses_failure'])

        if (num_analyses_avail > 0) and (num_analyses_ready < num_analyses_avail):
            response.status_code = 202  # signal to caller: please request again
        else:
            response.status_code = 200  # request is as complete as possible

        return response


@register_card_view_class(ART_SERIES)
class PlotCardView(SimpleCardView):

    template_name_pattern = "analysis/plot_card_{template_flavor}.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_warnings = []
        analyses_success = context['analyses_success']

        #
        # order analyses such that surface analyses are coming last (plotted on top)
        analyses_success_list = filter_and_order_analyses(analyses_success)
        data_sources_dict = []

        # Special case: It can happen that there is one surface with a successful analysis
        # but the only measurement's analysis has no success. In this case there is also
        # no successful analysis to display because the surface has only one measurement.

        nb_analyses_success = len(analyses_success_list)
        if nb_analyses_success == 0:
            #
            # Prepare plot, controls, and table with special values..
            #
            context['data_sources'] = json.dumps([])
            context['categories'] = json.dumps([
                {
                    'title': "Averages / Measurements",
                    'key': "subject_name",
                },
                {
                    'title': "Data Series",
                    'key': "series_name",
                },
            ])
            context['extra_warnings'] = extra_warnings
            return context

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
        def get_axis_type(key):
            return first_analysis_result.get(key) or "linear"

        context.update(dict(
            x_axis_label=x_axis_label,
            y_axis_label=y_axis_label,
            x_axis_type=get_axis_type('xscale'),
            y_axis_type=get_axis_type('yscale'),
            output_backend=settings.BOKEH_OUTPUT_BACKEND))

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

            if xunit is None:
                analysis_xscale = 1
            else:
                try:
                    analysis_xscale = ureg.convert(1, result_metadata['xunit'], xunit)
                except UndefinedUnitError as exc:
                    err_msg = f"Cannot convert x units when displaying results for analysis with id {analysis.id}. "\
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
                #series_url = default_storage.url(f'{analysis.storage_prefix}/series-{series_idx}.json')

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
                data_sources_dict += [dict(
                    source_name=f'analysis-{analysis.id}',
                    subject_name=subject_display_name,
                    subject_name_index=analysis_idx,
                    subject_name_has_parent=parent_analysis is not None,
                    series_name=series_name,
                    series_name_index=series_name_idx,
                    has_parent=has_parent,  # can be used for the legend
                    xScaleFactor=analysis_xscale,
                    yScaleFactor=analysis_yscale,
                    url=series_url,
                    color=curr_color,
                    dash=curr_dash,
                    width=line_width,
                    alpha=alpha,
                    showSymbols=show_symbols,
                    visible=series_name_idx in visible_series_indices,  # independent of subject
                    is_surface_analysis=is_surface_analysis,
                    is_topography_analysis=is_topography_analysis
                )]

        context['data_sources'] = json.dumps(data_sources_dict)
        context['categories'] = json.dumps([
            {
                'title': "Averages / Measurements",
                'key': "subject_name",
            },
            {
                'title': "Data Series",
                'key': "series_name",
            },
        ])
        context['extra_warnings'] = extra_warnings

        return context


def renew_analyses_view(request):
    """Renew existing analyses.
    :param request:
    :return: HTTPResponse
    """
    if not request.is_ajax():
        raise Http404

    request_method = request.POST
    user = request.user

    if user.is_anonymous:
        raise PermissionDenied()

    try:
        analyses_ids = request_method.getlist('analyses_ids[]')
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'error in request data'}, status=400)

    try:
        analyses_ids = [int(x) for x in analyses_ids ]
        analyses = Analysis.objects.filter(id__in=analyses_ids)
    except Exception:
        return JsonResponse({'error': 'error in request data'}, status=400)

    allowed = all(a.is_visible_for_user(user) for a in analyses)

    if allowed:
        new_analyses = [renew_analysis(a) for a in analyses]
        status = 200

        #
        # create a collection of analyses such that points to all analyses
        #
        analyses_str = f"{len(analyses)} analyses" if len(analyses) > 1 else "one analysis"
        collection = AnalysisCollection.objects.create(name=f"Recalculation of {analyses_str}.",
                                                       combined_task_state=Analysis.PENDING,
                                                       owner=user)
        collection.analyses.set(new_analyses)
        #
        # Each finished analysis checks whether related collections are finished, see "topobank.taskapp.tasks"
        #
    else:
        status = 403

    return JsonResponse({}, status=status)


def submit_analyses_view(request):
    """Requests analyses.
    :param request:
    :return: HTTPResponse
    """
    if not request.is_ajax():
        raise Http404

    request_method = request.POST
    user = request.user

    if user.is_anonymous:
        raise PermissionDenied()

    # args_dict = request_method
    try:
        function_id = int(request_method.get('function_id'))
        subjects = request_method.get('subjects')
        function_kwargs_json = request_method.get('function_kwargs_json')
        function_kwargs = json.loads(function_kwargs_json)
        subjects = subjects_from_dict(subjects)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'error in request data'}, status=400)

    #
    # Interpret given arguments
    #
    function = AnalysisFunction.objects.get(id=function_id)

    allowed = True
    for subject in subjects:
        allowed &= subject.is_shared(user)
        if not allowed:
            break

    if allowed:
        analyses = [request_analysis(user, function, subject, **function_kwargs) for subject in subjects]

        status = 200

        #
        # create a collection of analyses such that points to all analyses
        #
        collection = AnalysisCollection.objects.create(name=f"{function.name} for {len(subjects)} subjects.",
                                                       combined_task_state=Analysis.PENDING,
                                                       owner=user)
        collection.analyses.set(analyses)
        #
        # Each finished analysis checks whether related collections are finished, see "topobank.taskapp.tasks"
        #
    else:
        status = 403

    return JsonResponse({}, status=status)


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

        card = dict(function=function, subjects=subjects)

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
            analysis_result_type = reg.get_analysis_result_type_for_function_name(function.name)
            cards.append(dict(id=f"card-{function.pk}",
                              function=function,
                              analysis_result_type=analysis_result_type,
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
