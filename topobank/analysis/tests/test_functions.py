import numpy as np
import math
import pytest

from PyCo.Topography import Topography, NonuniformLineScan

from topobank.analysis.functions import (
    IncompatibleTopographyException,
    height_distribution, slope_distribution, curvature_distribution,
    power_spectrum, autocorrelation, variable_bandwidth,
    contact_mechanics)

###############################################################################
# Tests for line scans
###############################################################################

def test_height_distribution_simple_line_scan():

    x = np.array((1,2,3))
    y = 2*x

    info = dict(unit='nm')

    t = NonuniformLineScan(x,y,info=info).detrend(detrend_mode='center')

    result = height_distribution(t)

    assert list(result.keys()) == ['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series']

    assert result['name'] == 'Height distribution'
    assert result['scalars'] == {
            'Mean Height': 0,
            'RMS Height': math.sqrt(4./3),
    }

    assert result['xlabel'] == 'Height'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == 'nm'
    assert result['yunit'] == 'nm⁻¹'

    assert len(result['series']) == 2

    exp_bins = np.array([-1, 1]) # expected values for height bins
    exp_height_dist_values = [1./6,2./6] # expected values
    series0 = result['series'][0]
    np.testing.assert_almost_equal(series0['x'], exp_bins)
    np.testing.assert_almost_equal(series0['y'], exp_height_dist_values)

    # not testing gauss values yet since number of points is unknown
    # proposal: use a well tested function instead of own formula

def test_slope_distribution_simple_line_scan():

    x = np.array((1,2,3,4))
    y = -2*x

    t = NonuniformLineScan(x, y).detrend(detrend_mode='center')

    result = slope_distribution(t, bins=3)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Slope distribution'
    assert result['scalars'] == {
            'Mean Slope (x direction)': -2.,  # absolut value of slope
            'RMS Slope (x direction)': 2., # absolut value of slope
    }

    assert result['xlabel'] == 'Slope'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == '1'
    assert result['yunit'] == '1'

    assert len(result['series']) == 2

    exp_bins = np.array([-2.33333333333, -2, -1.66666666666]) # for slopes
    exp_slope_dist_values = [0, 3, 0] # integral with dx=1/3 results to 1
    series0 = result['series'][0]
    np.testing.assert_almost_equal(series0['x'], exp_bins)
    np.testing.assert_almost_equal(series0['y'], exp_slope_dist_values)

    # not testing gauss values yet since number of points is unknown
    # proposal: use a well tested function instead of own formula

def test_curvature_distribution_simple_line_scan():

    unit = 'nm'
    x = np.arange(10)
    y = -2*x**2 # constant curvature

    t = NonuniformLineScan(x, y, info=dict(unit=unit)).detrend(detrend_mode='center')

    bins = np.array((-4.75,-4.25,-3.75,-3.25)) # special for this test in order to know results
    result = curvature_distribution(t, bins=bins)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Curvature distribution'

    assert pytest.approx(result['scalars']['Mean Curvature']) == -4
    assert pytest.approx(result['scalars']['RMS Curvature']) == 4

    assert result['xlabel'] == 'Curvature'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == '{}⁻¹'.format(unit)
    assert result['yunit'] == unit

    assert len(result['series']) == 2

    exp_bins = (bins[1:]+bins[:-1])/2
    exp_curv_dist_values = [0, 2, 0]

    # integral over dx= should be 1
    assert np.trapz(exp_curv_dist_values, exp_bins) == pytest.approx(1)


    series0 = result['series'][0]
    np.testing.assert_almost_equal(series0['x'], exp_bins)
    np.testing.assert_almost_equal(series0['y'], exp_curv_dist_values)

    # not testing gauss values yet since number of points is unknown
    # proposal: use a well tested function instead of own formula

def test_power_spectrum_simple_nonuniform_linescan():

    unit = 'nm'
    x = np.arange(10)
    y = -2*x**2 # constant curvature

    t = NonuniformLineScan(x, y, info=dict(unit=unit)).detrend(detrend_mode='center')

    result = power_spectrum(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xunit', 'yunit', 'xscale', 'yscale', 'series'])

    assert result['name'] == 'Power-spectral density (PSD)'

    assert result['xlabel'] == 'Wavevector'
    assert result['ylabel'] == 'PSD'
    assert result['xunit'] == '{}⁻¹'.format(unit)
    assert result['yunit'] == '{}³'.format(unit)

    assert len(result['series']) == 1

    s0, = result['series']

    assert s0['name'] == '1D PSD along x'

    # TODO Also check values here as integration test?

def test_autocorrelation_simple_nonuniform_topography():

    x = np.arange(5)
    h = 2*x

    info = dict(unit='nm')

    t = NonuniformLineScan(x, h, info=info).detrend('center')

    result = autocorrelation(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xscale', 'yscale', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Height-difference autocorrelation function (ACF)'

    # TODO Check result values for autocorrelation

def test_variable_bandwidth_simple_nonuniform_linescan():

    x = np.arange(5)
    h = 2 * x
    info = dict(unit='nm')

    t = NonuniformLineScan(x, h, info=info).detrend('center')

    result = variable_bandwidth(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xscale', 'yscale', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Variable-bandwidth analysis'
    # TODO Check result values for bandwidht


###############################################################################
# Tests for 2D topographies
###############################################################################

def test_height_distribution_simple_2D_topography():

    unit = 'nm'
    info = dict(unit=unit)

    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2*y+0*x # only slope in y direction

    t = Topography(arr, (10,5), info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    # bins = [-10., -8., -6., -4., -2.,  0.,  2.,  4.,  6.,  8., 10.]

    result = height_distribution(t, bins=10)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Height distribution'

    assert pytest.approx(result['scalars']['Mean Height']) == 0.
    assert pytest.approx(result['scalars']['RMS Height']) == np.sqrt(33)

    assert result['xlabel'] == 'Height'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == unit
    assert result['yunit'] == '{}⁻¹'.format(unit)

    assert len(result['series']) == 2

    exp_bins = np.array([-8.1, -6.3, -4.5, -2.7, -0.9,  0.9,  2.7,  4.5,  6.3,  8.1]) # for heights
    exp_height_dist_values = np.ones((10,))*1/(10*1.8) # each interval has width of 1.8, 10 intervals
    series0 = result['series'][0]

    assert series0['name'] == 'Height distribution'

    np.testing.assert_almost_equal(series0['x'], exp_bins)
    np.testing.assert_almost_equal(series0['y'], exp_height_dist_values)

    # TODO not testing gauss values yet since number of points is unknown
    # proposal: use a well tested function instead of own formula


def test_slope_distribution_simple_2D_topography():

    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2*y+0*x # only slope in y direction

    t = Topography(arr, (10,5)).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = slope_distribution(t, bins=3)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Slope distribution'

    assert pytest.approx(result['scalars']['Mean Slope (x direction)']) == 0.
    assert pytest.approx(result['scalars']['Mean Slope (y direction)']) == -4.
    assert pytest.approx(result['scalars']['RMS Slope (x direction)']) == 0.
    assert pytest.approx(result['scalars']['RMS Slope (y direction)']) == 4.

    assert result['xlabel'] == 'Slope'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == '1'
    assert result['yunit'] == '1'

    assert len(result['series']) == 4

    exp_bins_x = np.array([-1./3, 0, 1./3]) # for slopes
    exp_slope_dist_values_x = [0, 3, 0]
    series0 = result['series'][0]

    assert series0['name'] == 'Slope distribution (x direction)'

    np.testing.assert_almost_equal(series0['x'], exp_bins_x)
    np.testing.assert_almost_equal(series0['y'], exp_slope_dist_values_x)

    exp_bins_y = np.array([-4-1. / 3, -4, -4+1. / 3])  # for slopes
    exp_slope_dist_values_y = [0, 3, 0]
    series2 = result['series'][2]

    assert series2['name'] == 'Slope distribution (y direction)'

    np.testing.assert_almost_equal(series2['x'], exp_bins_y)
    np.testing.assert_almost_equal(series2['y'], exp_slope_dist_values_y)

    # TODO not testing gauss values yet since number of points is unknown
    # proposal: use a well tested function instead of own formula

def test_curvature_distribution_simple_2D_topography():

    unit = 'nm'
    info = dict(unit=unit)

    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2*y+0*x # only slope in y direction

    t = Topography(arr, (10,5), info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = curvature_distribution(t, bins=3)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Curvature distribution'

    assert pytest.approx(result['scalars']['Mean Curvature']) == 0.
    assert pytest.approx(result['scalars']['RMS Curvature']) == 0.

    assert result['xlabel'] == 'Curvature'
    assert result['ylabel'] == 'Probability'
    assert result['xunit'] == '{}⁻¹'.format(unit)
    assert result['yunit'] == unit

    assert len(result['series']) == 2

    s0, s1 = result['series']

    exp_bins = np.array([-1./3, 0, 1./3]) # for curvatures
    exp_curvature_dist_values = [0, 3, 0]

    assert s0['name'] == 'Curvature distribution'

    np.testing.assert_almost_equal(s0['x'], exp_bins)
    np.testing.assert_almost_equal(s0['y'], exp_curvature_dist_values)

    assert s1['name'] == 'RMS curvature'
    # Not testing gaussian here

def test_curvature_distribution_simple_2D_topography_periodic():

    unit = 'nm'
    info = dict(unit=unit)

    y = np.arange(100).reshape((1, -1))
    x = np.arange(100).reshape((-1, 1))

    arr = np.sin(y/2/np.pi) # only slope in y direction, second derivative is -sin

    t = Topography(arr, (100,100), periodic=True, info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = curvature_distribution(t, bins=3)

    assert sorted(result.keys()) == sorted(['name', 'scalars', 'xlabel', 'ylabel', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Curvature distribution'

    assert pytest.approx(result['scalars']['Mean Curvature']) == 0.


def test_power_spectrum_simple_2D_topography():

    unit = 'nm'
    info = dict(unit=unit)

    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2 * y + 0 * x  # only slope in y direction
    t = Topography(arr, (10, 5), info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = power_spectrum(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xunit', 'yunit', 'xscale', 'yscale', 'series'])

    assert result['name'] == 'Power-spectral density (PSD)'

    assert result['xlabel'] == 'Wavevector'
    assert result['ylabel'] == 'PSD'
    assert result['xunit'] == '{}⁻¹'.format(unit)
    assert result['yunit'] == '{}³'.format(unit)

    assert len(result['series']) == 3

    s0, s1, s2 = result['series']

    assert s0['name'] == 'q/π × 2D PSD'
    assert s1['name'] == '1D PSD along x'
    assert s2['name'] == '1D PSD along y'

    # TODO Also check values here as integration test?

def test_autocorrelation_simple_2D_topography():
    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2 * y + 0 * x  # only slope in y direction
    info = dict(unit='nm')

    t = Topography(arr, (10, 5), info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = autocorrelation(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xscale', 'yscale', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Height-difference autocorrelation function (ACF)'

    # TODO Check result values for autocorrelation

def test_variable_bandwidth_simple_2D_topography():
    y = np.arange(10).reshape((1, -1))
    x = np.arange(5).reshape((-1, 1))

    arr = -2 * y + 0 * x  # only slope in y direction

    info = dict(unit='nm')
    t = Topography(arr, (10, 5), info=info).detrend('center')

    # resulting heights follow this function: h(x,y)=-4y+9

    result = variable_bandwidth(t)

    assert sorted(result.keys()) == sorted(['name', 'xlabel', 'ylabel', 'xscale', 'yscale', 'xunit', 'yunit', 'series'])

    assert result['name'] == 'Variable-bandwidth analysis'
    # TODO Check result values for bandwidht

def test_contact_mechanics_incompatible_topography():

    x = np.arange(10)
    arr = 2*x
    info = dict(unit='nm')
    t = NonuniformLineScan(x,arr, info=info).detrend("center")

    with pytest.raises(IncompatibleTopographyException):
        contact_mechanics(t)

