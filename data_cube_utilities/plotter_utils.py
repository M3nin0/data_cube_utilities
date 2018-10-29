from datetime import datetime
import numpy as np
import pandas as pd
import datacube as dc
import xarray as xr
from xarray.ufuncs import logical_and as xr_and
from xarray.ufuncs import logical_or as xr_or
from rasterstats import zonal_stats
import pylab
import matplotlib as mpl
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab
import matplotlib.ticker as ticker
from matplotlib.ticker import FuncFormatter
from matplotlib.colors import LinearSegmentedColormap
import seaborn as sns
from scipy import stats, exp
from scipy.stats import norm
from scipy.signal import gaussian
from scipy.ndimage import filters
from scipy.optimize import curve_fit
from scipy.interpolate import spline, CubicSpline
from sklearn import linear_model
import calendar, datetime, time
import pytz
from scipy import stats
import warnings

from .dc_mosaic import ls7_unpack_qa
from .curve_fitting import gaussian_fit, poly_fit
from .scale import xr_scale, np_scale
from .dc_utilities import ignore_warnings, perform_timeseries_analysis

from scipy.interpolate import interp1d


def impute_missing_data_1D(data1D):
    """
    This function returns the data in the same format as it was
    passed in, but with missing values either masked out or imputed with appropriate values
    (currently only using a linear trend). Many linear plotting functions for 1D data often
    (and should) only connect contiguous,  non-nan data points. This leaves gaps in the
    piecewise linear plot, which are sometimes graphically undesirable.

    Parameters
    ----------
    data: numpy.ndarray
        A 1D NumPy array for which missing values are to be masked or imputed
        suitably for at least matplotlib plotting. If formatting for other libraries such
        as seaborn or plotly is necessary, add that formatting requirement as a parameter.
    """
    nan_mask = ~np.isnan(data1D)
    x = np.arange(len(data1D))
    x_no_nan = x[nan_mask]
    data_no_nan = data1D[nan_mask]
    if len(x_no_nan) >= 2:
        f = interp1d(x_no_nan, data_no_nan)
        # Select points for interpolation.
        interpolation_x_mask = (x_no_nan[0] <= x) & (x <= x_no_nan[-1])
        interpolation_x = x[interpolation_x_mask]
        data1D_interp = np.arange(len(data1D), dtype=np.float32)
        # The ends of data1D may contain NaNs that must be included.
        end_nan_inds = x[(x <= x_no_nan[0]) | (x_no_nan[-1] <= x)]
        data1D_interp[end_nan_inds] = np.nan
        data1D_interp[interpolation_x_mask] = f(interpolation_x)
        return data1D_interp
    else:  # Cannot interpolate with a single non-nan point.
        return data1D


## Datetime functions ##

def n64_to_epoch(timestamp):
    ts = pd.to_datetime(str(timestamp))
    time_format = "%Y-%m-%d"
    ts = ts.strftime(time_format)
    epoch = int(time.mktime(time.strptime(ts, time_format)))
    return epoch


def np_dt64_to_str(np_datetime, fmt='%Y-%m-%d'):
    """Converts a NumPy datetime64 object to a string based on a format string supplied to pandas strftime."""
    return pd.to_datetime(str(np_datetime)).strftime(fmt)


def tfmt(x, pos=None):
    return time.strftime("%Y-%m-%d", time.gmtime(x))


## End datetime functions ##

def regression_massage(ds):
    t_len = len(ds["time"])
    s_len = len(ds["latitude"]) * len(ds["longitude"])
    flat_values = ds.values.reshape(t_len * s_len)
    return list(zip(list(map(n64_to_epoch, ds.time.values)), flat_values))


def remove_nans(aList):
    i = 0
    while i < len(aList):
        if np.isnan(aList[i][1]):
            del aList[i]
            i = 0
        else:
            i += 1
    return aList


def full_linear_regression(ds):
    myList = regression_massage(ds)
    myList = remove_nans(myList)
    myList = sorted(myList, key=lambda tup: tup[0])
    time, value = zip(*myList)
    value = [int(x) for x in value]
    value = np.array(value)
    value.astype(int)
    time = np.array(time)
    time.astype(int)
    return list(zip(time, value))


def xarray_plot_data_vars_over_time(dataset, colors=['orange', 'blue']):
    """
    Plot a line plot of all data variables in an xarray.Dataset on a shared set of axes.

    Parameters
    ----------
    dataset: xarray.Dataset
        The Dataset containing data variables to plot. The only dimension and coordinate must be 'time'.
    colors: list
        A list of strings denoting colors for each data variable's points.
        For example, 'red' or 'blue' are acceptable.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    data_var_names = sorted(list(dataset.data_vars))
    len_dataset = dataset.time.size
    nan_mask = np.full(len_dataset, True)
    for i, data_arr_name in enumerate(data_var_names):
        data_arr = dataset[data_arr_name]
        nan_mask = nan_mask & data_arr.notnull().values
        plt.plot(data_arr[nan_mask], marker='o', c=colors[i])
    times = dataset.time.values
    date_strs = np.array(list(map(lambda time: np_dt64_to_str(time), times)))
    plt.xticks(np.arange(len(date_strs[nan_mask])), date_strs[nan_mask],
               rotation=45, ha='right', rotation_mode='anchor')
    plt.legend(data_var_names, loc='upper right')
    plt.show()


def xarray_scatterplot_data_vars(dataset, figure_kwargs={'figsize': (12, 6)}, colors=['blue', 'orange'], markersize=5):
    """
    Plot a scatterplot of all data variables in an xarray.Dataset on a shared set of axes.
    Currently requires a 'time' coordinate, which constitutes the x-axis.

    Parameters
    ----------
    dataset: xarray.Dataset
        The Dataset containing data variables to plot.
    frac_dates: float
        The fraction of dates to label on the x-axis.
    figure_kwargs: dict
        A dictionary of kwargs for matplotlib figure creation.
    colors: list
        A list of strings denoting abbreviated colors for each data variable's points.
        For example, 'r' is red and 'b' is blue.
    markersize: float
        The size of markers in the scatterplot.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    plt.figure(**figure_kwargs)
    data_var_names = list(dataset.data_vars)
    len_dataset = dataset.time.size
    nan_mask = np.full(len_dataset, True)
    for i, data_arr in enumerate(dataset.data_vars.values()):
        if len(list(dataset.dims)) > 1:
            dims_to_check_for_nulls = [dim for dim in list(dataset.dims) if dim != 'time']
            nan_mask = nan_mask & data_arr.notnull().any(dim=dims_to_check_for_nulls).values
        else:
            nan_mask = data_arr.notnull().values
        times = data_arr.to_dataframe().index.get_level_values('time').values
        plt.scatter(stats.rankdata(times, method='dense') - 1, data_arr.values.flatten(), c=colors[i], s=markersize)
    unique_times = dataset.time.values
    date_strs = np.array(list(map(lambda time: np_dt64_to_str(time), unique_times)))
    plt.xticks(np.arange(len(date_strs))[nan_mask], date_strs[nan_mask],
               rotation=45, ha='right', rotation_mode='anchor')
    plt.xlabel('time')
    plt.legend(data_var_names, loc='upper right')
    plt.show()


def xarray_plot_ndvi_boxplot_wofs_lineplot_over_time(dataset, resolution=None, colors=['orange', 'blue']):
    """
    For an xarray.Dataset, plot a boxplot of NDVI and line plot of WOFS across time.

    Parameters
    ----------
    dataset: xarray.Dataset
        A Dataset formatted as follows:
            coordinates: time, latitude, longitude.
            data variables: ndvi, wofs
    resolution: str
        Denotes the resolution of aggregation. Only options are None or 'weekly'.
    colors: list
        A list of strings denoting colors for each data variable's points.
        For example, 'red' or 'blue' are acceptable.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    plotting_data = dataset.stack(lat_lon=('latitude', 'longitude'))
    time_agg_str = 'weekofyear' if resolution is not None and resolution == 'weekly' else 'time'
    if time_agg_str != 'time':
        plotting_data = plotting_data.groupby('time.' + time_agg_str).mean(dim='time')
    fig, ax = plt.subplots(figsize=(9, 6))
    ndvi_box_color, wofs_line_color = ('orange', 'blue')
    times = plotting_data[time_agg_str].values

    # NDVI boxplot boxes
    # The data formatted for matplotlib.pyplot.boxplot().
    ndvi_formatted_data = xr.DataArray(np.full_like(plotting_data.ndvi.values, np.nan))
    for i, time in enumerate(times):
        ndvi_formatted_data.loc[i, :] = plotting_data.loc[{time_agg_str: time}].ndvi.values
    ndvi_nan_mask = ~np.isnan(ndvi_formatted_data)
    filtered_formatted_data = []  # Data formatted for matplotlib.pyplot.boxplot().
    acq_inds_to_keep = []  # Indices of acquisitions to keep. Other indicies contain all nan values.
    for i, (d, m) in enumerate(zip(ndvi_formatted_data, ndvi_nan_mask)):
        if len(d[m] != 0):
            filtered_formatted_data.append(d[m])
            acq_inds_to_keep.append(i)
    times_no_nan = times[acq_inds_to_keep]
    epochs = np.array(list(map(n64_to_epoch, times_no_nan))) if time_agg_str == 'time' else None
    x_locs = epochs if time_agg_str == 'time' else times_no_nan
    box_width = 0.5 * np.min(np.diff(x_locs))
    bp = ax.boxplot(filtered_formatted_data, widths=[box_width] * len(filtered_formatted_data),
                    positions=x_locs, patch_artist=True, boxprops=dict(facecolor=ndvi_box_color),
                    flierprops=dict(marker='o', markersize=0.25),
                    manage_xticks=False)  # `manage_xticks=False` to avoid excessive padding on the x-axis.

    # WOFS line
    wofs_formatted_data = xr.DataArray(np.full_like(plotting_data.wofs.values, np.nan))
    for i, time in enumerate(times):
        wofs_formatted_data.loc[i, :] = plotting_data.loc[{time_agg_str: time}].wofs.values
    wofs_line_plot_data = np.nanmean(wofs_formatted_data.values, axis=1)
    wofs_nan_mask = ~np.isnan(wofs_line_plot_data)
    line = ax.plot(x_locs, wofs_line_plot_data[wofs_nan_mask], c=wofs_line_color)

    date_strs = np.array(list(map(lambda time: np_dt64_to_str(time), times_no_nan))) if time_agg_str == 'time' else \
        naive_months_ticks_by_week(times_no_nan)
    x_labels = date_strs
    plt.xticks(x_locs, x_labels, rotation=45, ha='right', rotation_mode='anchor')

    plt.legend(handles=[bp['boxes'][0], line[0]], labels=list(plotting_data.data_vars), loc='best')
    plt.tight_layout()
    plt.show()


def xarray_time_series_plot(dataset, plot_descs, x_coord='longitude',
                            y_coord='latitude', fig_params=None,
                            scale_params=None, fig=None, ax=None,
                            max_times_per_plot=None, show_legend=True,
                            title=None):
    """
    Plot data variables in an xarray.Dataset together in one figure, with different
    plot types for each (e.g. box-and-whisker plot, line plot, scatter plot), and
    optional curve fitting to aggregations along time. Handles data binned with
    xarray.Dataset methods resample() and groupby(). That is, it handles data
    binned along time (e.g. by week) or across years (e.g. by week of year).

    Parameters
    -----------
    dataset: xarray.Dataset
        A Dataset containing some bands like NDVI or WOFS.
        The primary coordinate must be 'time'.
    plot_descs: dict
        Dictionary mapping names of DataArrays in the Dataset to plot to
        dictionaries mapping aggregation types (e.g. 'mean', 'median') to
        lists of dictionaries mapping plot types
        (e.g. 'line', 'box', 'scatter') to keyword arguments for plotting.

        Aggregation happens within time slices and can be many-to-many or many-to-one.
        Some plot types require many-to-many aggregation, and some other plot types
        require
        many-to-one aggregation. Aggregation types can be any of
        ['mean', 'median', 'none'], with 'none' performing no aggregation.

        Plot types can be any of
        ['scatter', 'line', 'gaussian', 'poly', 'cubic_spline', 'box'].
        The plot type 'poly' requires a 'degree' entry mapping to an integer in its
        dictionary of keyword arguments.

        Here is an example:
        {'ndvi':{'mean':[{'line':{'color':'forestgreen', 'alpha':alpha}}],
                 'none':[{'box':{'boxprops':{'facecolor':'forestgreen','alpha':alpha},
                                 'showfliers':False}}]}}
        This example will create a green line plot of the mean of the 'ndvi' band
        as well as a green box plot of the 'ndvi' band.
    x_coord, y_coord: str
        Names of the x and y coordinates in `dataset`
        to use as tick and axis labels.
    fig_params: dict
        Figure parameters dictionary (e.g. {'figsize':(12,6)}). Used to create a Figure
        ``if fig is None and ax is None``. Note that in the case of multiple plots
        being created (see ``max_times_per_plot`` below), figsize will be the size
        of each plot - not the entire figure.
    scale_params: dict
        Currently not used.
        Dictionary mapping names of DataArrays to scaling methods
        (e.g. {'ndvi': 'std', 'wofs':'norm'}). The options are ['std', 'norm'].
        The option 'std' standardizes. The option 'norm' normalizes (min-max scales).
        Note that of these options, only normalizing guarantees that the y values will be
        in a fixed range - namely [0,1].
    fig: matplotlib.figure.Figure
        The figure to use for the plot.
        If only `fig` is supplied, the Axes object used will be the first. This
        argument is ignored if ``max_times_per_plot`` is less than the number of times.
    ax: matplotlib.axes.Axes
        The axes to use for the plot. This argument is ignored if
        ``max_times_per_plot`` is less than the number of times.
    max_times_per_plot: int
        The maximum number of times per plot. If specified, one plot will be generated for
        each group of this many times. The plots will be arranged in a row-major grid.
    show_legend: bool
        Whether or not to show the legend.
    title: str
        The title of each subplot. Note that a date range enclosed in parenthesis
        will be postpended whether this is specified or not.

    Returns
    -------
    fig: matplotlib.figure.Figure
        The figure containing the plot grid.

    Raises
    ------
    ValueError:
        If an aggregation type is not possible for a plot type

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    # Set default values for mutable data.
    fig_params = {} if fig_params is None else fig_params
    fig_params.setdefault('figsize', (18, 12))
    scale_params = {} if scale_params is None else scale_params

    # Lists of plot types that can and cannot accept many-to-one aggregation
    # for each time slice.
    plot_types_requiring_aggregation = ['line', 'gaussian', 'poly', 'cubic_spline']
    plot_types_handling_aggregation = ['scatter'] + plot_types_requiring_aggregation
    plot_types_not_handling_aggregation = ['box']
    all_plot_types = plot_types_requiring_aggregation + plot_types_handling_aggregation \
                     + plot_types_not_handling_aggregation

    # Aggregation types that aggregate all values for a given time to one value.
    many_to_one_agg_types = ['mean', 'median']
    # Aggregation types that aggregate to many values or do not aggregate.
    many_to_many_agg_types = ['none']
    all_agg_types = many_to_one_agg_types + many_to_many_agg_types

    # Determine how the data was aggregated, if at all.
    possible_time_agg_strs = ['week', 'weekofyear', 'month']
    time_agg_str = 'time'
    for possible_time_agg_str in possible_time_agg_strs:
        if possible_time_agg_str in list(dataset.coords):
            time_agg_str = possible_time_agg_str
            break
    # Make the data 2D - time and a stack of all other dimensions.
    non_time_dims = list(set(dataset.dims) - {time_agg_str})
    all_plotting_bands = list(plot_descs.keys())
    all_plotting_data = dataset[all_plotting_bands].stack(stacked_data=non_time_dims)
    all_times = all_plotting_data[time_agg_str].values
    # Mask out times for which no data variable to plot has any non-NaN data.
    nan_mask_data_vars = list(all_plotting_data[all_plotting_bands] \
                              .notnull().data_vars.values())
    for i, data_var in enumerate(nan_mask_data_vars):
        time_nan_mask = data_var.values if i == 0 else time_nan_mask | data_var.values
    time_nan_mask = np.any(time_nan_mask, axis=1)
    times_not_all_nan = all_times[time_nan_mask]
    all_plotting_data = all_plotting_data.loc[{time_agg_str: times_not_all_nan}]

    # Scale
    # if scale_params denotes the scaling type for the whole Dataset, scale the Dataset.
    if isinstance(scale_params, str):
        all_plotting_data = xr_scale(all_plotting_data, scaling=scale_params)
    # else, it is a dictionary denoting how to scale each DataArray.
    elif len(scale_params) > 0:
        for data_arr_name, scaling in scale_params.items():
            all_plotting_data[data_arr_name] = \
                xr_scale(all_plotting_data[data_arr_name], scaling=scaling)

    # Handle the potential for multiple plots.
    max_times_per_plot = len(times_not_all_nan) if max_times_per_plot is None else \
        max_times_per_plot
    num_plots = int(np.ceil(len(times_not_all_nan) / max_times_per_plot))
    subset_num_cols = 2
    subset_num_rows = int(np.ceil(num_plots / subset_num_cols))
    if num_plots > 1:
        #         figsize = fig_params.pop('figsize')
        base_figsize = fig_params.pop('figsize', \
                                      figure_ratio(dataset, x_coord, y_coord,
                                                   fixed_width=10))
        figsize = [base * num for base, num in
                   zip(base_figsize, (subset_num_cols, subset_num_rows))]
        fig = plt.figure(figsize=figsize, **fig_params)

    # Create each plot.
    for time_ind, fig_ind in zip(range(0, len(times_not_all_nan), max_times_per_plot),
                                 range(num_plots)):
        lower_time_bound_ind, upper_time_bound_ind = \
            time_ind, min(time_ind + max_times_per_plot, len(times_not_all_nan))
        time_extents = times_not_all_nan[[lower_time_bound_ind, upper_time_bound_ind - 1]]
        # Retrieve or create the axes if necessary.
        if len(times_not_all_nan) <= max_times_per_plot:
            fig, ax = retrieve_or_create_fig_ax(fig, ax, **fig_params)
        else:
            ax = fig.add_subplot(subset_num_rows, subset_num_cols, fig_ind + 1)
        fig_times_not_all_nan = \
            times_not_all_nan[lower_time_bound_ind:upper_time_bound_ind]
        plotting_data = all_plotting_data.loc[{time_agg_str: fig_times_not_all_nan}]
        epochs = np.array(list(map(n64_to_epoch, fig_times_not_all_nan))) \
            if time_agg_str == 'time' else None
        x_locs = np_scale(epochs if time_agg_str == 'time' else fig_times_not_all_nan)

        # Data variable plots within each plot.
        data_arr_plots = []
        legend_labels = []
        # For each data array to plot...
        for data_arr_name, agg_dict in plot_descs.items():
            # For each aggregation type (e.g. 'mean', 'median')...
            for agg_type, plot_dicts in agg_dict.items():
                # For each plot for this aggregation type...
                for plot_dict in plot_dicts:
                    for plot_type, plot_kwargs in plot_dict.items():
                        assert plot_type in all_plot_types, \
                            r"For the '{}' DataArray: plot_type '{}' not recognized" \
                                .format(data_arr_name, plot_type)
                        full_data_arr_plotting_data = plotting_data[data_arr_name].values
                        # Any times with all nan data are ignored in any plot type.
                        data_arr_nan_mask = \
                            np.any(~np.isnan(full_data_arr_plotting_data), axis=1)

                        # Skip plotting this data variable if it does not have
                        # enough data to plot.
                        if skip_plot(np.sum(data_arr_nan_mask), plot_type, plot_kwargs):
                            continue

                        # Remove times with all nan data.
                        data_arr_plotting_data = \
                            full_data_arr_plotting_data[data_arr_nan_mask]
                        # Large scales for x_locs can break the curve fitting
                        # for some reason.
                        data_arr_x_locs = x_locs[data_arr_nan_mask]

                        # Some plot types require aggregation.
                        if plot_type in plot_types_requiring_aggregation:
                            if agg_type not in many_to_one_agg_types:
                                raise ValueError("For the '{}' DataArray: the plot type "
                                                 "'{}' requires aggregation (currently using '{}'). "
                                                 "Please pass any of {} as the aggregation type "
                                                 "or change the plot type.".format(data_arr_name, \
                                                                                   plot_type, agg_type,
                                                                                   many_to_one_agg_types))
                        # Some plot types cannot accept many-to-one aggregation.
                        if plot_type not in plot_types_handling_aggregation:
                            if agg_type not in many_to_many_agg_types:
                                raise ValueError("For the '{}' DataArray: "
                                                 "the plot type '{}' doesn't accept aggregation "
                                                 "(currently using '{}'). Please pass any of {} as "
                                                 "the aggregation type or change the plot type."
                                                 .format(data_arr_name, plot_type, agg_type,
                                                         many_to_many_agg_types))

                        if agg_type == 'mean':
                            y = ignore_warnings(np.nanmean, \
                                                data_arr_plotting_data, axis=1)
                        elif agg_type == 'median':
                            y = ignore_warnings(np.nanmedian, \
                                                data_arr_plotting_data, axis=1)
                        elif agg_type == 'none':
                            y = data_arr_plotting_data

                        # Create specified plot types.
                        plot_type_str = ""  # Used to label the legend.
                        if plot_type == 'scatter':
                            data_arr_plots.append(ax.scatter(data_arr_x_locs, y,
                                                             **plot_kwargs))
                            plot_type_str += 'scatterplot'
                        elif plot_type == 'line':
                            data_arr_plots.append(ax.plot(data_arr_x_locs, y,
                                                          **plot_kwargs)[0])
                            plot_type_str += 'lineplot'
                        elif plot_type == 'box':
                            boxplot_nan_mask = ~np.isnan(y)
                            # Data formatted for matplotlib.pyplot.boxplot().
                            filtered_formatted_data = []
                            for i, (d, m) in enumerate(zip(y, boxplot_nan_mask)):
                                if len(d[m] != 0):
                                    filtered_formatted_data.append(d[m])
                            box_width = 0.5 * np.min(np.diff(data_arr_x_locs)) \
                                if len(data_arr_x_locs) > 1 else 0.5
                            # Provide default arguments.
                            plot_kwargs.setdefault('boxprops', dict(facecolor='orange'))
                            plot_kwargs.setdefault('flierprops', dict(marker='o', \
                                                                      markersize=0.5))
                            plot_kwargs.setdefault('showfliers', False)
                            # `manage_xticks=False` to avoid excessive padding on x-axis.
                            bp = ax.boxplot(filtered_formatted_data,
                                            widths=[box_width] * len(filtered_formatted_data),
                                            positions=data_arr_x_locs, patch_artist=True,
                                            manage_xticks=False, **plot_kwargs)
                            data_arr_plots.append(bp['boxes'][0])
                            plot_type_str += 'boxplot'
                        elif plot_type == 'gaussian':
                            data_arr_plots.append(
                                plot_curvefit(data_arr_x_locs, y, fit_type=plot_type,
                                              plot_kwargs=plot_kwargs, ax=ax))
                            plot_type_str += 'gaussian fit'
                        elif plot_type == 'poly':
                            assert 'degree' in plot_kwargs, \
                                r"For the '{}' DataArray: When using 'poly' as " \
                                "the fit type, the fit kwargs must have 'degree'" \
                                "specified.".format(data_arr_name)
                            data_arr_plots.append(
                                plot_curvefit(data_arr_x_locs, y, fit_type=plot_type,
                                              plot_kwargs=plot_kwargs, ax=ax))
                            plot_type_str += 'degree {} polynomial fit' \
                                .format(plot_kwargs['degree'])
                        elif plot_type == 'cubic_spline':
                            data_arr_plots.append(
                                plot_curvefit(data_arr_x_locs, y, fit_type=plot_type,
                                              plot_kwargs=plot_kwargs, ax=ax))
                            plot_type_str += 'cubic spline fit'
                        plot_type_str += ' of {}'.format(agg_type) \
                            if agg_type != 'none' else ''
                        legend_labels.append('{} of {}' \
                                             .format(plot_type_str, data_arr_name))

        # Label the axes and create the legend.
        date_strs = \
            np.array(list(map(lambda time: np_dt64_to_str(time), fig_times_not_all_nan))) \
                if time_agg_str == 'time' else \
                naive_months_ticks_by_week(fig_times_not_all_nan) \
                    if time_agg_str in ['week', 'weekofyear'] else \
                    month_ints_to_month_names(fig_times_not_all_nan)
        plt.xticks(x_locs, date_strs, rotation=45, ha='right', rotation_mode='anchor')
        if show_legend:
            plt.legend(handles=data_arr_plots, labels=legend_labels, loc='best')
        title_postpend = " ({} to {})".format(date_strs[0], date_strs[-1])
        title_prepend = "Figure {}".format(fig_ind) if title is None else title
        plt.title(title_prepend + title_postpend)
        plt.tight_layout()
    return fig


## Curve fitting ##

def plot_curvefit(x, y, fit_type, x_smooth=None, n_pts=200, fig_params={}, plot_kwargs={}, fig=None, ax=None):
    """
    Plots a curve fit given x values, y values, a type of curve to plot, and parameters for that curve.

    Parameters
    ----------
    x: np.ndarray
        A 1D NumPy array. The x values to fit to.
    y: np.ndarray
        A 1D NumPy array. The y values to fit to.
    fit_type: str
        The type of curve to fit. One of ['poly', 'gaussian', 'cubic_spline'].
        The option 'poly' plots a polynomial fit. The option 'gaussian' plots a Gaussian fit.
        The option 'cubic_spline' plots a cubic spline fit.
    x_smooth: list-like
        The exact x values to interpolate for. Supercedes `n_pts`.
    n_pts: int
        The number of evenly spaced points spanning the range of `x` to interpolate for.
    fig_params: dict
        Figure parameters dictionary (e.g. {'figsize':(12,6)}).
        Used to create a Figure ``if fig is None and ax is None``.
    plot_kwargs: dict
        The kwargs for the call to ``matplotlib.axes.Axes.plot()``.
    fig: matplotlib.figure.Figure
        The figure to use for the plot. The figure must have at least one Axes object.
        You can use the code ``fig,ax = plt.subplots()`` to create a figure with an associated Axes object.
        The code ``fig = plt.figure()`` will not provide the Axes object.
        The Axes object used will be the first.
    ax: matplotlib.axes.Axes
        The axes to use for the plot.

    Returns
    -------
    lines: matplotlib.lines.Line2D
        Can be used as a handle for a matplotlib legend (i.e. plt.legend(handles=...)) among other things.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    # Avoid modifying the original arguments.
    fig_params, plot_kwargs = fig_params.copy(), plot_kwargs.copy()

    fig_params.setdefault('figsize', (12, 6))
    plot_kwargs.setdefault('linestyle', '-')

    # Retrieve or create the axes if necessary.
    fig, ax = retrieve_or_create_fig_ax(fig, ax, **fig_params)
    if x_smooth is None:
        x_smooth = np.linspace(x.min(), x.max(), n_pts)
    if fit_type == 'gaussian':
        y_smooth = gaussian_fit(x, y, x_smooth)
    elif fit_type == 'poly':
        assert 'degree' in plot_kwargs.keys(), "When plotting a polynomal fit, there must be" \
                                               "a 'degree' entry in the plot_kwargs parameter."
        degree = plot_kwargs.pop('degree')
        y_smooth = poly_fit(x, y, degree, x_smooth)
    elif fit_type == 'cubic_spline':
        cs = CubicSpline(x, y)
        y_smooth = cs(x_smooth)
    return ax.plot(x_smooth, y_smooth, **plot_kwargs)[0]


## End curve fitting ##

def plot_band(dataset, figsize=(20, 15), fontsize=24, legend_fontsize=24):
    """
    Plots several statistics over time - including mean, median, linear regression of the
    means, Gaussian smoothed curve of means, and the band enclosing the 25th and 75th percentiles.
    This is very similar to the output of the Comet Time Series Toolset (https://github.com/CosmiQ/CometTS).

    Parameters
    ----------
    dataset: xarray.DataArray
        An xarray `DataArray` containing time, latitude, and longitude coordinates.
    figsize: tuple
        A 2-tuple of the figure size in inches for the entire figure.
    fontsize: int
        The font size to use for text.
    """
    # Calculations
    times = dataset.time.values
    epochs = np.sort(np.array(list(map(n64_to_epoch, times))))
    x_locs = (epochs - epochs.min()) / (epochs.max() - epochs.min())
    means = dataset.mean(dim=['latitude', 'longitude'], skipna=True).values
    medians = dataset.median(dim=['latitude', 'longitude'], skipna=True).values
    mask = ~np.isnan(means) & ~np.isnan(medians)

    plt.figure(figsize=figsize)
    ax = plt.gca()

    # Shaded Area (percentiles)
    with warnings.catch_warnings():
        # Ignore warning about encountering an All-NaN slice. Some acquisitions have all-NaN values.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        quarter = np.nanpercentile(
            dataset.values.reshape((
                len(dataset['time']),
                len(dataset['latitude']) * len(dataset['longitude']))),
            25,
            axis=1
        )
        three_quarters = np.nanpercentile(
            dataset.values.reshape((
                len(dataset['time']),
                len(dataset['latitude']) * len(dataset['longitude']))),
            75,
            axis=1
        )
    np.array(quarter)
    np.array(three_quarters)
    ax.grid(color='lightgray', linestyle='-', linewidth=1)
    fillcolor = 'gray'
    fillalpha = 0.4
    plt.fill_between(x_locs, quarter, three_quarters, interpolate=False, color=fillcolor, alpha=fillalpha,
                     label="25th and 75th percentile band")

    # Medians
    plt.plot(x_locs, medians, color="black", marker="o", linestyle='None', label="Medians")

    # The Actual Plot
    plt.plot(x_locs, means, color="blue", label="Mean")

    # Linear Regression (on mean)
    m, b = np.polyfit(x_locs[mask], means[mask], 1)
    plt.plot(x_locs, m * x_locs + b, '-', color="red", label="linear regression of means", linewidth=3.0)

    # Gaussian Curve
    plot_curvefit(x_locs[mask], means[mask], fit_type='gaussian', ax=ax,
                  plot_kwargs=dict(linestyle='-', label="Gaussian smoothed of means",
                                   alpha=1, color='limegreen', linewidth=3.0))

    # Formatting
    date_strs = np.array(list(map(lambda time: np_dt64_to_str(time), times[mask])))
    ax.grid(color='k', alpha=0.1, linestyle='-', linewidth=1)
    ax.xaxis.set_major_formatter(FuncFormatter(tfmt))
    plt.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=legend_fontsize)
    plt.xticks(x_locs, date_strs, rotation=45, fontsize=fontsize)
    plt.yticks(fontsize=fontsize)
    ax.set_xlabel('Time', fontsize=fontsize)
    ax.set_ylabel('Value', fontsize=fontsize)
    plt.show()


def plot_pixel_qa_value(dataset, platform, values_to_plot, bands="pixel_qa", plot_max=False, plot_min=False):
    times = dataset.time.values
    mpl.style.use('seaborn')
    plt.figure(figsize=(20, 15))
    quarters = []
    three_quarters = []
    percentiles = []

    for i, v in enumerate(values_to_plot):
        _xarray = ls7_unpack_qa(dataset.pixel_qa, values_to_plot[i])
        y = _xarray.mean(dim=['latitude', 'longitude'])
        times = dataset.time.values.astype(float)
        std_dev = np.std(y)
        std_dev = std_dev.values
        b = gaussian(len(times), std_dev)
        ga = filters.convolve1d(y, b / b.sum(), mode="reflect")
        ga = interpolate_gaps(ga, limit=3)
        plt.plot(times, ga, '-', label="Gaussian ", alpha=1, color='black')

        x_smooth = np.linspace(times.min(), times.max(), 200)
        y_smooth = spline(times, ga, x_smooth)
        plt.plot(x_smooth, y_smooth, '-', label="Gaussian Smoothed", alpha=1, color='cyan')

        for i, q in enumerate(_xarray):
            quarters.append(np.nanpercentile(_xarray, 25))
            three_quarters.append(np.nanpercentile(_xarray, 75))

        ax = plt.gca()
        ax.grid(color='lightgray', linestyle='-', linewidth=1)
        fillcolor = 'gray'
        fillalpha = 0.4
        linecolor = 'gray'
        linealpha = 0.6
        plt.fill_between(times, y, quarters, interpolate=False, color=fillcolor, alpha=fillalpha)
        plt.fill_between(times, y, three_quarters, interpolate=False, color=fillcolor, alpha=fillalpha)
        plt.plot(times, quarters, color=linecolor, alpha=linealpha)
        plt.plot(times, three_quarters, color=linecolor, alpha=linealpha)

        medians = _xarray.median(dim=['latitude', 'longitude'])
        plt.scatter(times, medians, color='mediumpurple', label="medians", marker="D")

        m, b = np.polyfit(times, y, 1)
        plt.plot(times, m * times + b, '-', color="red", label="linear regression")
        plt.style.use('seaborn')

        plt.plot(times, y, marker="o")
        plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
        plt.xticks(rotation=90)

    ## Color utils ##


def convert_name_rgb_255(color):
    """
    Converts a name of a matplotlib color to a list of rgb values in the range [0,255].
    Else, returns the original argument.

    Parameters
    ----------
    color: str or list (size 3)
        The color name to convert or a list of red, green, and blue already in range [0,255].
    """
    return [255 * rgb for rgb in mpl.colors.to_rgb(color)] if isinstance(color, str) else color


def norm_color(color):
    color = convert_name_rgb_255(color)
    if len(color) == 3:
        color = [rgb / 255 for rgb in color]
    return color


## End color utils ##

## Matplotlib colormap functions ##

def create_discrete_color_map(data_range, colors, th=None, cmap_name='my_cmap'):
    """
    Creates a discrete matplotlib LinearSegmentedColormap with thresholds for color changes.

    Parameters
    ----------
    data_range: list
        A 2-tuple of the minimum and maximum values the data may take.
    colors: list
        Colors to use between thresholds.
        Colors can be string names of matplotlib colors or 3-tuples of rgb values in range [0,255].
    th: list
        Threshold values separating colors, so `len(colors) == len(th)+1`.
        Must be in the range of `data_range` - noninclusive.
    cmap_name: str
        The name of the created colormap for matplotlib.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    # Normalize threshold values based on the data range.
    th_spacing = (data_range[1] - data_range[0]) / len(colors)

    if th is None:
        th = np.linspace(data_range[0] + th_spacing, data_range[1] - th_spacing, len(colors) - 1)
    th = list(map(lambda val: (val - data_range[0]) / (data_range[1] - data_range[0]), th))
    colors = list(map(norm_color, colors))
    th = [0.0] + th + [1.0]

    cdict = {}
    # These are fully-saturated red, green, and blue - not the matplotlib colors for 'red', 'green', and 'blue'.
    primary_colors = ['red', 'green', 'blue']
    # Get the 3-tuples of rgb values for the colors.
    color_rgbs = [(mpl.colors.to_rgb(color) if isinstance(color, str) else color) for color in colors]
    # For each color entry to go into the color dictionary...
    for primary_color_ind, primary_color in enumerate(primary_colors):
        cdict_entry = [None] * len(th)
        # For each threshold (as well as 0.0 and 1.0), specify the values for this primary color.
        for row_ind, th_ind in enumerate(range(len(th))):
            # Get the two colors that this threshold corresponds to.
            th_color_inds = [0, 0] if th_ind == 0 else \
                [len(colors) - 1, len(colors) - 1] if th_ind == len(th) - 1 else \
                    [th_ind - 1, th_ind]
            primary_color_vals = [color_rgbs[th_color_ind][primary_color_ind] for th_color_ind in th_color_inds]
            cdict_entry[row_ind] = (th[th_ind],) + tuple(primary_color_vals)
        cdict[primary_color] = cdict_entry
    cmap = LinearSegmentedColormap(cmap_name, cdict)
    return cmap


def create_gradient_color_map(data_range, colors, positions=None, cmap_name='my_cmap'):
    """
    Creates a gradient colormap with a LinearSegmentedColormap. Currently only creates linear gradients.

    Parameters
    ----------
    data_range: list-like
        A 2-tuple of the minimum and maximum values the data may take.
    colors: list of str or list of tuple
        Colors can be string names of matplotlib colors or 3-tuples of rgb values in range [0,255].
        The first and last colors are placed at the beginning and end of the colormap, respectively.
    positions: list-like
        The values which are colored with corresponding colors in `colors`,
        except the first and last colors, so `len(positions) == len(colors)-2`.
        Positions must be in the range of `data_range` - noninclusive.
        If no positions are provided, the colors are evenly spaced.
    cmap_name: str
        The name of the created colormap for matplotlib.

    Examples
    --------
    Creating a linear gradient colormap of red, green, and blue, with even spacing between them:
        create_gradient_color_map(data_range=(0,1), positions=(0.5,), colors=('red', 'green', 'blue'))
    Which can also be done without specifying `positions`:
        create_gradient_color_map(data_range=(0,1), colors=('red', 'green', 'blue'))
    """
    # Normalize position values based on the data range.
    if positions is None:
        range_size = data_range[1] - data_range[0]
        spacing = range_size / (len(colors) - 1)
        positions = [spacing * i for i in range(1, len(colors) - 1)]
    else:
        positions = list(map(lambda val: (val - data_range[0]) / (data_range[1] - data_range[0]), positions))

    colors = list(map(norm_color, colors))  # Normalize color values for colormap creation.
    positions = [0.0] + positions + [1.0]

    cdict = {}
    # These are fully-saturated red, green, and blue - not the matplotlib colors for 'red', 'green', and 'blue'.
    primary_colors = ['red', 'green', 'blue']
    # Get the 3-tuples of rgb values for the colors.
    color_rgbs = [(mpl.colors.to_rgb(color) if isinstance(color, str) else color) for color in colors]
    cdict = {'red': [], 'green': [], 'blue': []}
    for pos, color in zip(positions, color_rgbs):
        cdict['red'].append((pos, color[0], color[0]))
        cdict['green'].append((pos, color[1], color[1]))
        cdict['blue'].append((pos, color[2], color[2]))
    return LinearSegmentedColormap(cmap_name, cdict)


## End matplotlib colormap functions ##

### Discrete color plotting (exclusive) ###

def binary_class_change_plot(dataarrays, x_coord='longitude', y_coord='latitude', mask=None,
                             colors=None, class_legend_label=None, width=10, fig=None, ax=None,
                             title=None, fig_kwargs={}, title_kwargs={}, imshow_kwargs={},
                             x_label_kwargs={}, y_label_kwargs={}, legend_kwargs={}):
    """
    Creates a figure showing one of the following, depending on the format of arguments:
        1. The change in the extents of a binary pixel classification in a region over time.
           Pixels are colored based on never, sometimes, or always being a member of the class.
           In this case, there are 3 regions - never, sometimes, and always.
        2. The change in the extents of a binary pixel classification in a region over time between
           two time periods. Pixels are colored based on a change in having zero or more than zero
           times in which they are members of the class between the time periods.
           In this case, there are 4 regions - (never,never),(never,some),(some,never),(some,some).

    Parameters
    ----------
    dataarrays: list-like of xarray.DataArray
        A list-like of one or two DataArrays of classification values
        to plot, which must be either 0 or 1.
    x_coord, y_coord: str
        Names of the x and y coordinates in `data` to use as tick and axis labels.
    mask: numpy.ndarray
        A NumPy array of the same shape as the dataarrays.
        The pixels for which it is `True` are colored `color_mask`.
    colors: list-like:
        A list-like of list-likes of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color.

        If `dataarrays` contains one DataArray, these are the colors for pixels.
        Provide 3 color entries - for never, sometimes, and always class membership, in that order.

        If `dataarrays` contains two DataArrays, these are the colors for pixels that have zero
        or more than zero times in which they are members of the class between the time periods.
        Provide 4 color entires - (never,never),(never,some),(some,never),(some,some) class membership.
    class_legend_label: str
        The class label on the legend. For example, `class_legend_label='Water'` would yield legend labels
        like "Never Water".
    width: numeric
        The width of the created ``matplotlib.figure.Figure``, if none is supplied in `fig`.
        The height will be set to maintain aspect ratio.
        Will be overridden by `'figsize'` in `fig_kwargs`, if present.
    fig: matplotlib.figure.Figure
        The figure to use for the plot.
        If `ax` is not supplied, the Axes object used will be the first.
    ax: matplotlib.axes.Axes
        The axes to use for the plot.
    title: str
        The title of the plot.
    fig_kwargs: dict
        The dictionary of keyword arguments used to build the figure.
    title_kwargs: dict
        The dictionary of keyword arguments used to format the title.
        Passed to `matplotlib.axes.Axes.set_title()`.
    imshow_kwargs: dict
        The dictionary of keyword arguments passed to `ax.imshow()`.
        You can pass a colormap here with the key 'cmap'.
    x_label_kwargs, y_label_kwargs: dict
        Dictionaries of keyword arguments for
        `Axes.set_xlabel()` and `Axes.set_ylabel()`, respectively.
        They cannot reference the same dictionary.
    legend_kwargs: dict
        The dictionary of keyword arguments passed to `ax.legend()`.

    Returns
    -------
    (fig,ax), pcts:
        A 2-tuple of the figure and axes followed by a list of either 3 or 4 percents of
        pixel membership, depending on whether `dataarray` contains one or two DataArrays.

        If `dataarrays` contains one DataArray, there are 3 percents for never, sometimes,
        and always class membership.

        If `dataarrays` contains two DataArrays, there are 4 percents for
        (never,never),(never,some),(some,never),(some,some) class membership.

    :Authors:
        John Rattz (john.c.rattz@ama-inc.com)
    """
    # Avoid modifying the original arguments.
    fig_kwargs, title_kwargs, legend_kwargs = \
        fig_kwargs.copy(), title_kwargs.copy(), legend_kwargs.copy()

    # Handle conversion of matplotlib color names to lists of rgb values (range [0,255] for plt.imshow()).
    colors = list(map(convert_name_rgb_255, colors))

    def get_none_chng_perm_masks(dataarray, time_dim='time'):
        """
        For a DataArray of binary classifications (0 or 1) with a 'time' dimension,
        get a list of masks indicating where the points are, in order, never, sometimes,
        or always a member of the class (1 indicates membership), considering only
        non-NaN values for those points.
        """
        # Get the sum of classifications across time.
        sum_cls = dataarray.sum(dim=time_dim)
        # The number of acquistions that were not nan for each point.
        num_times_not_nan = dataarray.count(dim=time_dim)
        # Find where pixels are permanent, changing, or never a member of the class.
        none_mask = sum_cls == 0
        chng_mask = xr_and(0 < sum_cls, sum_cls < num_times_not_nan)
        perm_mask = sum_cls == num_times_not_nan
        return [none_mask, chng_mask, perm_mask]

    # Assemble the color masks.
    masks = []
    if len(dataarrays) == 1:  # Determine extent change in one time period.
        dataarray = dataarrays[0]
        masks += get_none_chng_perm_masks(dataarray)
    else:  # Determine change between two time periods.
        baseline_da, analysis_da = dataarrays
        baseline_none_mask, baseline_chng_mask, baseline_perm_mask = get_none_chng_perm_masks(baseline_da)
        analysis_none_mask, analysis_chng_mask, analysis_perm_mask = get_none_chng_perm_masks(analysis_da)
        # Find where points are never a member of the class or are a member at one or more times.
        baseline_cls_ever = xr_or(baseline_chng_mask, baseline_perm_mask)
        analysis_cls_ever = xr_or(analysis_chng_mask, analysis_perm_mask)
        # Find where points change between never being a member of the class
        # and being a member at one or more times between the two periods.
        no_cls_no_cls_mask = xr_and(baseline_none_mask, analysis_none_mask)
        no_cls_cls_mask = xr_and(baseline_none_mask, analysis_cls_ever)
        cls_no_cls_mask = xr_and(baseline_cls_ever, analysis_none_mask)
        cls_cls_mask = xr_and(baseline_cls_ever, analysis_cls_ever)
        masks += [no_cls_no_cls_mask, no_cls_cls_mask, cls_no_cls_mask, cls_cls_mask]

    # Determine the overriding mask.
    y_x_shape = len(dataarrays[0][y_coord]), len(dataarrays[0][x_coord])
    mask = np.zeros(y_x_shape, dtype=np.bool) if mask is None else mask

    # Color the image with the masks.
    color_array = np.zeros((*y_x_shape, 3)).astype(np.int16)
    for i, mask in enumerate(masks):
        color_array[mask.values] = colors[i]

    fig_kwargs['figsize'] = fig_kwargs.get('figsize', figure_ratio(dataarrays[0], x_coord, y_coord,
                                                                   fixed_width=width))
    fig, ax = retrieve_or_create_fig_ax(fig, ax, **fig_kwargs)

    # Set the tick and axes labels.
    xarray_set_axes_labels(dataarrays[0], ax, x_coord=x_coord, y_coord=y_coord,
                           x_label_kwargs=x_label_kwargs, y_label_kwargs=y_label_kwargs)

    # Title the plot.
    if title is None:
        title = "Class Extents Change" if len(dataarrays) == 1 else \
            "Class Extents Change (Baseline/Analysis)"
    ax.set_title(title, **title_kwargs)

    # Create the legend.
    colors = [np.array(color) / 255 for color in colors]  # Colors must be in range [0,1] for color patches.
    if len(dataarrays) == 1:
        class_legend_label = "a Member of the Class" if class_legend_label is None else class_legend_label
        labels = list(map(lambda str: str.format(class_legend_label),
                          ['Never {}', 'Sometimes {}', 'Always {}']))
    else:
        class_legend_label = "Class Membership" if class_legend_label is None else class_legend_label
        labels = list(map(lambda str: str.format(class_legend_label, class_legend_label),
                          ['No {} to No {}', 'No {} to {}', '{} to No {}', '{} to {}']))
    color_patches = list(map(lambda color, label: mpatches.Patch(color=color, label=label), colors, labels))
    legend_kwargs.setdefault('loc', 'best')
    legend_kwargs['handles'] = color_patches
    ax.legend(**legend_kwargs)

    ax.imshow(color_array, **imshow_kwargs)

    # Calculate the percentage of pixels that are permanent, changing, or never members.
    pcts = [float((mask.sum() / (y_x_shape[0] * y_x_shape[1])).values) for mask in masks]

    return [fig, ax], pcts


## Threshold plotting ##

def intersection_threshold_plot(first, second, th, mask=None, color_none='black',
                                color_first='green', color_second='red',
                                color_both='white', color_mask='gray',
                                width=10, fig=None, ax=None, *args, **kwargs):
    """
    Given two dataarrays, create a threshold plot showing where zero, one, or both are within a threshold.

    Parameters
    ----------
    first, second: xarray.DataArray
        The DataArrays to compare.
    th: tuple
        A 2-tuple of the minimum (inclusive) and maximum (exclusive) threshold values, respectively.
    mask: numpy.ndarray
        A NumPy array of the same shape as the dataarrays. The pixels for which it is `True`
        are colored`color_mask`.
    color_none: list-like or str
        A list-like of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color. Used to color regions where
        neither first nor second have values within the threshold.
        Default color is black.
    color_first: list-like or str
        A list-like of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color. Used to color regions where
        only the first has values within the threshold.
        Default color is green.
    color_second: list-like or str
        A list-like of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color. Used to color regions where
        only the second has values within the threshold.
        Default color is red.
    color_both: list-like or str
        A list-like of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color. Used to color regions where
        both the first and second have values within the threshold.
        Default color is white.
    color_mask: list-like or str
        A list-like of 3 elements - red, green, and blue values in range [0,255],
        or the name of a matplotlib color. Used to color regions where `mask == True`.
        Overrides any other color a region may have.
        Default color is gray.
    width: int
        The width of the created ``matplotlib.figure.Figure``.
        The height will be set to maintain aspect ratio.
    fig: matplotlib.figure.Figure
        The figure to use for the plot.
        If `ax` is not supplied, the Axes object used will be the first.
    ax: matplotlib.axes.Axes
        The axes to use for the plot.
    *args: list
        Arguments passed to ``matplotlib.pyplot.imshow()``.
    **kwargs: dict
        Keyword arguments passed to ``matplotlib.pyplot.imshow()``.
    """
    # Handle conversion of matplotlib color names to lists of rgb values.
    color_none, color_first, color_second, color_both, color_mask = \
        list(map(convert_name_rgb_255, [color_none, color_first, color_second, color_both, color_mask]))

    # Determine the regions.
    first_in = np.logical_and(th[0] <= first, first < th[1])
    second_in = np.logical_and(th[0] <= second, second < th[1])
    both_in = np.logical_and(first_in, second_in)
    none_in = np.invert(both_in)
    # Determine the overriding mask.
    mask = np.zeros(first.shape).astype(bool) if mask is None else mask

    # The colors for each pixel.
    color_array = np.zeros((*first.shape, 3)).astype(np.int16)

    color_array[none_in] = color_none
    color_array[first_in] = color_first
    color_array[second_in] = color_second
    color_array[both_in] = color_both
    color_array[mask] = color_mask

    fig, ax = retrieve_or_create_fig_ax(fig, ax, figsize=figure_ratio(first, x_coord, y_coord, fixed_width=width))

    plt.title("Threshold: {} < x < {}".format(th[0], th[1]))

    max_num_ticks = 10  # Max ticks per axis.

    lon = first.longitude.values
    label_every = int(round(len(lon) / max_num_ticks))
    lon_labels = ["{0:.4f}".format(lon_val) for lon_val in lon[::label_every]]
    plt.xlabel('Longitude')
    plt.xticks(range(len(lon))[::label_every], lon_labels, rotation='vertical')

    lat = first.latitude.values
    label_every = int(round(len(lat) / max_num_ticks))
    lat_labels = ["{0:.4f}".format(lat_val) for lat_val in lat[::label_every]]
    plt.ylabel('Latitude')
    plt.yticks(range(len(lat))[::label_every], lat_labels)

    plt.imshow(color_array, *args, **kwargs)
    plt.show()

    ## End threshold plotting ##


### End discrete color plotting (exclusive)##

## Misc ##

def print_matrix(cell_value_mtx, cell_label_mtx=None, row_labels=None, col_labels=None,
                 show_row_labels=True, show_col_labels=True, show_cell_labels=True,
                 cmap=None, cell_val_fmt='2g', annot_kwargs={}, tick_fontsize=14,
                 x_axis_tick_kwargs=None, y_axis_tick_kwargs=None,
                 x_axis_ticks_position='default', y_axis_ticks_position='default',
                 fig=None, ax=None, heatmap_kwargs={}, fig_kwargs={}):
    """
    Prints a matrix as a heatmap.
    Inspired by https://gist.github.com/shaypal5/94c53d765083101efc0240d776a23823.

    Arguments
    ---------
    cell_value_mtx: numpy.ndarray
        A 2D NumPy array to be used as the cell values when coloring with the colormap.
    cell_label_mtx: numpy.ndarray
        A 2D NumPy array to be used as the cell labels.
    row_labels, col_labels: list
        A list of labels in the order they index the matrix rows and columns, respectively.
    show_row_labels, show_col_labels: bool
        Whether to show the row or column labels, respectively.
    show_cell_labels: bool
        Whether to show values as cell labels or not.
    cmap: matplotlib.colors.Colormap
        A matplotlib colormap used to color the cells based on `cell_value_mtx`.
    cell_val_fmt: str
        Formatting string for values in the matrix cells.
    annot_kwargs: dict
        Keyword arguments for ``ax.text`` for formatting cell annotation text.
    tick_fontsize: int
        The fontsize of tick labels. Overridden by `x_axis_tick_kwargs` and `y_axis_tick_kwargs`.
    x_axis_tick_kwargs, y_axis_tick_kwargs: dict
        Keyword arguments for x and y axis tick labels, respectively.
        Specifically, keyword arguments for calls to `ax.[x_axis,y_axis].set_ticklabels()`
        where `ax` is the `matplotlib.axes.Axes` object returned by `seaborn.heatmap()`.
    x_axis_ticks_position, y_axis_ticks_position: str
        The position of x and y axis ticks, respectively.
        For x_axis_ticks_position, possible values are ['top', 'bottom', 'both', 'default', 'none'].
        For y_axis_ticks_position, possible values are ['left', 'right', 'both', 'default', 'none'].
        See https://matplotlib.org/api/axis_api.html for more information.
    fig: matplotlib.figure.Figure
        The figure to use for the plot.
        If only `fig` is supplied, the Axes object used will be the first.
    ax: matplotlib.axes.Axes
        The axes to use for the plot.
    heatmap_kwargs: dict
        Dictionary of keyword arguments to `seaborn.heatmap()`.
        Overrides any other relevant parameters passed to this function.
        Some notable parameters include 'vmin', 'vmax', 'cbar', and 'cbar_kws'.
    fig_kwargs: dict
        The dictionary of keyword arguments used to build the figure.

    Returns
    -------
    fig, ax: matplotlib.figure.Figure, matplotlib.axes.Axes
        The figure and axes used for the plot.
    """
    cell_label_mtx = cell_value_mtx if cell_label_mtx is None else cell_label_mtx
    row_labels = [''] * cell_value_mtx.shape[0] if not show_row_labels else row_labels
    col_labels = [''] * cell_value_mtx.shape[1] if not show_col_labels else col_labels
    heatmap_kwargs.setdefault('cbar', False)

    df = pd.DataFrame(cell_value_mtx, index=row_labels, columns=col_labels)
    cell_labels = cell_label_mtx if show_cell_labels else None
    fig, ax = retrieve_or_create_fig_ax(fig, ax, **fig_kwargs)
    heatmap = sns.heatmap(df, cmap=cmap, annot=cell_labels, fmt=cell_val_fmt,
                          annot_kws=annot_kwargs, ax=ax, **heatmap_kwargs)
    if not show_row_labels:
        heatmap.set_yticks([])  # Ticks must be hidden explicitly.
    else:
        if y_axis_tick_kwargs is None:
            y_axis_tick_kwargs = dict(rotation=0, ha='right')
        y_axis_tick_kwargs.setdefault('fontsize', tick_fontsize)
        heatmap.yaxis.set_ticklabels(heatmap.yaxis.get_ticklabels(), **y_axis_tick_kwargs)
        heatmap.yaxis.set_ticks_position(y_axis_ticks_position)
        heatmap.yaxis.tick_left()  # Ticks may also appear on the right side otherwise.
    if not show_col_labels:
        heatmap.set_xticks([])
    else:
        if x_axis_tick_kwargs is None:
            x_axis_tick_kwargs = dict(rotation=45, ha='right')
        x_axis_tick_kwargs.setdefault('fontsize', tick_fontsize)
        heatmap.xaxis.set_ticklabels(heatmap.xaxis.get_ticklabels(), **x_axis_tick_kwargs)
        heatmap.xaxis.set_ticks_position(x_axis_ticks_position)
    return fig, ax


def xarray_imshow(data, x_coord='longitude', y_coord='latitude', width=10, fig=None, ax=None, use_colorbar=True,
                  cbar_labels=None, use_legend=False, legend_labels=None, fig_kwargs={},
                  imshow_kwargs={}, x_label_kwargs={}, y_label_kwargs={},
                  cbar_kwargs={}, nan_color='white', legend_kwargs={}):
    """
    Shows a heatmap of an xarray DataArray with only latitude and longitude dimensions.
    Different from `data.plot.imshow()` in that this sets axes ticks and labels - including
    labeling "Latitude" and "Longitude" - and shows a colorbar.

    Parameters
    ----------
    data: xarray.DataArray
        The xarray.DataArray containing only latitude and longitude coordinates.
    x_coord, y_coord: str
        Names of the x and y coordinates in `data` to use as tick and axis labels.
    width: numeric
        The width of the created ``matplotlib.figure.Figure``, if none is supplied in `fig`.
        The height will be set to maintain aspect ratio.
        Will be overridden by `'figsize'` in `fig_kwargs`, if present.
    fig: matplotlib.figure.Figure
        The figure to use for the plot.
        If `ax` is not supplied, the Axes object used will be the first.
    ax: matplotlib.axes.Axes
        The axes to use for the plot.
    use_colorbar: bool
        Whether or not to create a colorbar to the right of the axes.
    cbar_labels: list
        A list of strings to label the colorbar.
    use_legend: bool
        Whether or not to create a legend showing labels for unique values.
        Only use if you are sure you have a low number of unique values.
    legend_labels: dict
        A mapping of values to legend labels.
    fig_kwargs: dict
        The dictionary of keyword arguments used to build the figure.
    imshow_kwargs: dict
        The dictionary of keyword arguments passed to `plt.imshow()`.
        You can pass a colormap here with the key 'cmap'.
    x_label_kwargs, y_label_kwargs: dict
        Dictionaries of keyword arguments for
        `Axes.set_xlabel()` and `Axes.set_ylabel()`, respectively.
        They cannot reference the same dictionary.
    cbar_kwargs: dict
        The dictionary of keyword arguments passed to `plt.colorbar()`.
        Some parameters of note include 'ticks', which is a list of values to place ticks at.
    nan_color: str or list-like
        The color used for NaN regions. Can be a string name of a matplotlib color or
        a 3-tuple (list-like) of rgb values in range [0,255].
    legend_kwargs: dict
        The dictionary of keyword arguments passed to `plt.legend()`.

    Returns
    -------
    fig, ax, im, cbar: matplotlib.figure.Figure, matplotlib.axes.Axes,
                       matplotlib.image.AxesImage,  matplotlib.colorbar.Colorbar
        The figure and axes used as well as the image returned by `pyplot.imshow()` and the colorbar.
        If `use_colorbar == False`, `cbar` will be `None`.
    """
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    # Avoid modifying the original arguments.
    fig_kwargs, imshow_kwargs, legend_kwargs = \
        fig_kwargs.copy(), imshow_kwargs.copy(), legend_kwargs.copy()

    nan_color = norm_color(nan_color)  # Normalize color value for matplotlib.

    fig_kwargs['figsize'] = \
        fig_kwargs.get('figsize', figure_ratio(data, x_coord, y_coord,
                                               fixed_width=width))
    fig, ax = retrieve_or_create_fig_ax(fig, ax, **fig_kwargs)

    if use_colorbar:
        imshow_kwargs.setdefault('vmin', np.nanmin(data.values))
        imshow_kwargs.setdefault('vmax', np.nanmax(data.values))

    # Handle display of NaN values.
    data_arr = data.values
    masked_array = np.ma.array(data_arr, mask=np.isnan(data_arr))
    imshow_kwargs.setdefault('interpolation', 'nearest')
    cmap = imshow_kwargs.setdefault('cmap', plt.get_cmap('viridis'))
    cmap.set_bad(nan_color)
    im = ax.imshow(masked_array, **imshow_kwargs)

    xarray_set_axes_labels(data, ax, x_coord, y_coord,
                           x_label_kwargs, y_label_kwargs)

    # Create a colorbar.
    if use_colorbar:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="7.5%", pad=0.05)
        cbar = fig.colorbar(im, ax=ax, cax=cax, **cbar_kwargs)
        if cbar_labels is not None:
            cbar.ax.set_yticklabels(cbar_labels)
    else:
        cbar = None

    # Create a legend.
    if use_legend:
        unique_values = np.unique(data.values)
        unique_values = unique_values[~np.isnan(unique_values)]
        if legend_labels is None:
            legend_labels = ["{}".format(value) for value in unique_values]
        else:
            legend_labels = [legend_labels.get(value, "{}".format(value)) for value in unique_values]
        colors = [im.cmap(im.norm(unique_values)) for unique_values in unique_values]
        patches = [mpatches.Patch(color=colors[i], label=legend_labels[i])
                   for i in range(len(legend_labels))]
        legend_kwargs.setdefault('loc', 'best')
        legend_kwargs['handles'] = patches
        ax.legend(**legend_kwargs)

    return fig, ax, im, cbar


def xarray_set_axes_labels(data, ax, x_coord='longitude', y_coord='latitude',
                           x_label_kwargs={}, y_label_kwargs={}, fontsize=10):
    """
    Sets tick locations and labels for x and y axes on a `matplotlib.axes.Axes` object
    such that the tick labels do not overlap. By default, labels x-axis as "Longitude"
    and y-axis as "Latitude".

    Parameters
    ----------
    data: xarray.Dataset or xarray.DataArray
        The xarray Dataset or DataArray containing latitude and longitude coordinates.
    x_coord, y_coord: str
        Names of the x and y coordinates in `data` to use as tick and axis labels.
    ax: matplotlib.axes.Axes
        The matplotlib Axes object to set tick locations and labels for.
    fontsize: numeric
        The fontsize of the tick labels. This determines the number of ticks used.
    x_label_kwargs, y_label_kwargs: dict
        Dictionaries of keyword arguments for
        `Axes.set_xlabel()` and `Axes.set_ylabel()`, respectively.
    """
    import string
    # Avoid modifying the original arguments.
    x_label_kwargs, y_label_kwargs = x_label_kwargs.copy(), y_label_kwargs.copy()

    bbox = ax.get_window_extent()
    width, height = bbox.width, bbox.height

    x_vals = data[x_coord].values
    label_every = max(1, int(round(10 * len(x_vals) * fontsize / width)))
    x_labels = ["{0:.4f}".format(x_val) for x_val in x_vals[::label_every]]
    x_label_kwargs.setdefault('xlabel', string.capwords(x_coord))
    ax.set_xlabel(**x_label_kwargs)
    ax.set_xticks(range(len(x_vals))[::label_every])
    ax.set_xticklabels(x_labels, rotation=45, fontsize=fontsize)

    y_vals = data[y_coord].values
    label_every = max(1, int(round(10 * len(y_vals) * fontsize / height)))
    y_labels = ["{0:.4f}".format(y_val) for y_val in y_vals[::label_every]]
    y_label_kwargs.setdefault('ylabel', string.capwords(y_coord))
    ax.set_ylabel(**y_label_kwargs)
    ax.set_yticks(range(len(y_vals))[::label_every])
    ax.set_yticklabels(y_labels, fontsize=fontsize)


def figure_ratio(data, x_coord='latitude', y_coord='longitude', fixed_width=10):
    """
    Returns a tuple of the width and height necessary for a figure showing data
    of a given shape to maintain aspect ratio.

    Parameters
    ----------
    data: xarray.Dataset or xarray.DataArray or list-like
        Can be either of the following:
        1. A list-like of x and y dimension sizes, respectively
        2. An xarray Dataset or DataArray containing x and y dimensions
    x_coord, y_coord: str
        Names of the x and y coordinates in `data`.
    """
    width = fixed_width
    if isinstance(data, xr.Dataset) or isinstance(data, xr.DataArray):
        height = fixed_width * (len(data[y_coord]) / len(data[x_coord]))
    else:
        height = fixed_width * (data[1] / data[0])
    return (width, height)


def retrieve_or_create_fig_ax(fig=None, ax=None, **fig_params):
    """
    Returns appropriate matplotlib Figure and Axes objects given Figure and/or Axes objects.
    If neither is supplied, a new figure will be created with associated axes.
    If only `fig` is supplied, `(fig,fig.axes[0])` is returned. That is, the first Axes object will be used (and created if necessary).
    If `ax` is supplied, `(fig, ax)` is returned.

    Returns
    -------
    fig, ax: matplotlib.figure.Figure, matplotlib.axes.Axes
        The figure and the axes of that figure.
    """
    if ax is None:
        if fig is None:
            fig, ax = plt.subplots(**fig_params)
        else:
            if len(fig.axes) == 0:
                fig.add_axes([1, 1, 1, 1])
            ax = fig.axes[0]
    return fig, ax


def skip_plot(n_pts, plot_type, kwargs={}):
    """Returns a boolean denoting whether to skip plotting data given the number of points it contains."""
    min_pts_dict = {'scatter': 1, 'box': 1, 'gaussian': 3, 'poly': 1, 'cubic_spline': 3, 'line': 2}
    min_pts = min_pts_dict[plot_type]
    if plot_type == 'poly':
        assert 'degree' in kwargs.keys(), "When plotting a polynomal fit, there must be" \
                                          "a 'degree' entry in the fit_kwargs parameter."
        degree = kwargs['degree']
        min_pts = min_pts + degree
    return n_pts < min_pts


def remove_non_unique_ordered_list_str(ordered_list):
    """
    Sets all occurrences of a value in an ordered list after its first occurence to ''.
    For example, ['a', 'a', 'b', 'b', 'c'] would become ['a', '', 'b', '', 'c'].
    """
    prev_unique_str = ""
    for i in range(len(ordered_list)):
        current_str = ordered_list[i]
        if current_str != prev_unique_str:
            prev_unique_str = current_str
        else:
            ordered_list[i] = ""
    return ordered_list


# For February, assume leap years are included.
days_per_month = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def get_weeks_per_month(num_weeks):
    """
    Including January, give 5 weeks to every third month - accounting for 
    variation between 52 and 54 weeks in a year by adding weeks to the last 3 months.
    """
    last_months_num_weeks = None
    if num_weeks <= 52:
        last_months_num_weeks = [5, 4, 4]
    elif num_weeks == 53:
        last_months_num_weeks = [5, 4, 5]
    elif num_weeks == 54:
        last_months_num_weeks = [5, 5, 5]
    return {month_int: num_weeks for (month_int, num_weeks) in
            zip(days_per_month.keys(), [5, 4, 4] * 3 + last_months_num_weeks)}


month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def month_ints_to_month_names(month_ints):
    """
    Converts ordinal numbers for months (in range [1,12]) to their 3-letter names.
    """
    return [month_names[i - 1] for i in month_ints]


def week_ints_to_month_names(week_ints):
    """
    Converts ordinal numbers for weeks (in range [1,54]) to their months' 3-letter names.
    """
    weeks_per_month = get_weeks_per_month(max(week_ints))
    week_month_strs = []
    for week_int in week_ints:
        month_int = -1
        for current_month_int, current_month_weeks in weeks_per_month.items():
            week_int -= current_month_weeks
            if week_int <= 0:
                month_int = current_month_int
                break
        week_month_strs.append(month_names[month_int - 1])
    return week_month_strs


def naive_months_ticks_by_week(week_ints=None):
    """
    Given a list of week numbers (in range [1,54]), returns a list of month strings separated by spaces.
    Covers 54 weeks if no list-like of week numbers is given.
    This is only intended to be used for labeling axes in plotting.
    """
    month_ticks_by_week = []
    if week_ints is None:  # Give month ticks for all weeks.
        month_ticks_by_week = week_ints_to_month_names(list(range(54)))
    else:
        month_ticks_by_week = remove_non_unique_ordered_list_str(week_ints_to_month_names(week_ints))
    return month_ticks_by_week