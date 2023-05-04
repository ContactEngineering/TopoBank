import logging
import math
from collections import OrderedDict

from bokeh import palettes as palettes
from django.contrib.contenttypes.models import ContentType

_log = logging.getLogger(__name__)


def mangle_sheet_name(s: str) -> str:
    """Return a string suitable for a sheet name in Excel/Libre Office.

    :param s: sheet name
    :return: string which should be suitable for sheet names
    """

    replacements = {
        ':': '',
        '[': '(',
        ']': ')',
        '*': '',
        '?': '',
        "'": '"',
        "\\": ""
    }

    for x, y in replacements.items():
        s = s.replace(x, y)

    return s


def round_to_significant_digits(x, num_dig_digits):
    """Round given number to given number of significant digits

    Parameters
    ----------
    x: flost
        Number to be rounded
    num_dig_digits: int
        Number of significant digits


    Returns
    -------
    Rounded number.

    For NaN, NaN is returned.
    """
    if math.isnan(x):
        return x
    try:
        return round(x, num_dig_digits - int(math.floor(math.log10(abs(x)))) - 1)
    except ValueError:
        return x


def filter_and_order_analyses(analyses):
    """Order analyses such that surface analyses are coming last (plotted on top).

    The analyses are filtered that that surface analyses
    are only included if there are more than 1 measurement.

    Parameters
    ----------
    analyses: list of Analysis instances
        Analyses to be filtered and sorted.

    Returns
    -------
    Ordered list of analyses. Analyses for measurements
    are listed directly after corresponding surface.
    """
    from topobank.manager.models import Surface, SurfaceCollection, Topography

    surface_ct = ContentType.objects.get_for_model(Surface)
    surfacecollection_ct = ContentType.objects.get_for_model(SurfaceCollection)
    topography_ct = ContentType.objects.get_for_model(Topography)

    sorted_analyses = []

    #
    # Order analyses by surface
    # such that for each surface the analyses are ordered by subject id
    #
    analysis_groups = OrderedDict()  # always the same order of surfaces for same list of subjects
    for topography_analysis in sorted([analysis for analysis in analyses if analysis.subject_type == topography_ct],
                                      key=lambda analysis: analysis.subject_id):
        surface = topography_analysis.subject.surface
        if not surface in analysis_groups:
            analysis_groups[surface] = []
        analysis_groups[surface].append(topography_analysis)

    #
    # Process groups and collect analyses which are implicitly sorted
    #
    analyses_of_surfaces = sorted([a for a in analyses if a.subject_type == surface_ct],
                                  key=lambda a: a.subject_id)
    surfaces_of_surface_analyses = [a.subject for a in analyses_of_surfaces]
    for surface, topography_analyses in analysis_groups.items():
        try:
            # Is there an analysis for the corresponding surface?
            surface_analysis_index = surfaces_of_surface_analyses.index(surface)
            surface_analysis = analyses_of_surfaces[surface_analysis_index]
            if surface.num_topographies() > 1:
                # only show average for surface if more than one topography
                sorted_analyses.append(surface_analysis)
                surface_analysis_index = len(sorted_analyses) - 1  # last one
        except ValueError:
            # No analysis given for surface, so skip
            surface_analysis_index = None

        #
        # Add topography analyses whether there was a surface analysis or not
        # This will result in same order of topography analysis, no matter whether there was a surface analysis
        #
        if surface_analysis_index is None:
            sorted_analyses.extend(topography_analyses)
        else:
            # Insert corresponding topography analyses after surface analyses
            sorted_analyses = sorted_analyses[:surface_analysis_index + 1] + topography_analyses \
                              + sorted_analyses[surface_analysis_index + 1:]

    #
    # Finally add analyses for surface collections, if any
    #
    for collection_analysis in sorted([a for a in analyses if a.subject_type == surfacecollection_ct],
                                      key=lambda a: a.subject_id):
        sorted_analyses.append(collection_analysis)

    return sorted_analyses


def palette_for_topographies(nb_topographies):
    """Return a palette to distinguish topographies by color in a plot.

    Parameters
    ----------
    nb_topographies: int
        Number of topographies
    """
    if nb_topographies <= 10:
        topography_colors = palettes.Category10_10
    else:
        topography_colors = [palettes.Plasma256[k * 256 // nb_topographies] for k in range(nb_topographies)]
        # we don't want to have yellow as first color
        topography_colors = topography_colors[nb_topographies // 2:] + topography_colors[:nb_topographies // 2]
    return topography_colors
