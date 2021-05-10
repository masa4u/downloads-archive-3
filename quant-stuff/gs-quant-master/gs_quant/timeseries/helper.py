"""
Copyright 2019 Goldman Sachs.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""
import datetime
import inspect
import logging
from enum import Enum, IntEnum
from functools import wraps
from typing import Optional, Union, List, Iterable

import pandas as pd

from gs_quant.api.gs.data import QueryType
from gs_quant.data import DataContext
from gs_quant.datetime.relative_date import RelativeDate
from gs_quant.entities.entity import EntityType
from gs_quant.errors import MqValueError


def _create_enum(name, members):
    return Enum(name, {n.upper(): n.lower() for n in members}, module=__name__)


def _create_int_enum(name, mappings):
    return IntEnum(name, {k.upper(): v for k, v in mappings.items()})


def _to_offset(tenor: str) -> pd.DateOffset:
    import re
    matcher = re.fullmatch('(\\d+)([dwmy])', tenor)
    if not matcher:
        raise MqValueError('invalid tenor ' + tenor)

    ab = matcher.group(2)
    if ab == 'd':
        name = 'days'
    elif ab == 'w':
        name = 'weeks'
    elif ab == 'm':
        name = 'months'
    else:
        assert ab == 'y'
        name = 'years'

    kwarg = {name: int(matcher.group(1))}
    return pd.DateOffset(**kwarg)


Interpolate = _create_enum('Interpolate', ['intersect', 'step', 'nan', 'zero', 'time'])
Returns = _create_enum('Returns', ['simple', 'logarithmic', 'absolute'])
SeriesType = _create_enum('SeriesType', ['prices', 'returns'])
CurveType = _create_enum('CurveType', ['prices', 'excess_returns'])


class Window:
    """
    Create a Window with size and ramp up to use.

    :param w: window size
    :param r: ramp up value. Defaults to the window size.
    :return: new window object

    **Usage**

    The window size and ramp up value can either the number of observations or a string representation of the time
    period.

    **Examples**

    Window size is :math:`22` observations and the ramp up value is :math:`10`:

    >>> Window(22, 10)

    Window size is one month and the ramp up size is one week:

    >>> Window('1m', '1w')

    """

    def __init__(self, w: Union[int, str, None] = None, r: Union[int, str, None] = None):
        self.w = w
        self.r = w if r is None else r

    def as_dict(self):
        return {
            'w': self.w,
            'r': self.r
        }

    @classmethod
    def from_dict(cls, obj):
        return Window(w=obj.get('w'), r=obj.get('r'))


def _check_window(series_length: int, window: Window):
    if series_length > 0 and isinstance(window.w, int) and isinstance(window.r, int):
        if window.w <= 0:
            raise MqValueError('Window value must be greater than zero.')
        if window.r > series_length or window.r < 0:
            raise MqValueError('Ramp value must be less than the length of the series and greater than zero.')


def apply_ramp(x: pd.Series, window: Window) -> pd.Series:
    _check_window(len(x), window)
    if isinstance(window.w, int) and window.w > len(x):  # does not restrict window size when it is a DataOffset
        return pd.Series([])
    if isinstance(window.r, pd.DateOffset):
        return x.loc[x.index[0] + window.r:]
    else:
        return x[window.r:]


def normalize_window(x: Union[pd.Series, pd.DataFrame], window: Union[Window, int, str, None],
                     default_window: int = None) -> Window:
    if default_window is None:
        default_window = len(x)

    if isinstance(window, int):
        window = Window(window, window)
    elif isinstance(window, str):
        window = Window(_to_offset(window), _to_offset(window))
    else:
        if window is None:
            window = Window(default_window, 0)
        else:
            if isinstance(window.w, str):
                window = Window(_to_offset(window.w), window.r)
            if isinstance(window.r, str):
                window = Window(window.w, _to_offset(window.r))
            if window.w is None:
                window = Window(default_window, window.r)

    _check_window(default_window, window)
    return window


def plot_function(fn):
    # Indicates that fn should be exported to plottool as a pure function.
    fn.plot_function = True
    return fn


def plot_session_function(fn):
    fn.plot_function = True
    fn.requires_session = True
    return fn


def check_forward_looking(pricing_date, source, name="function"):
    if pricing_date is not None or source != 'plottool':
        return
    if DataContext.current.end_date <= datetime.date.today():
        msg = (f'{name}() requires a forward looking date range e.g. [0d, 3y]. '
               'Please update the date range via the date picker.')
        raise MqValueError(msg)


def plot_measure(asset_class: Optional[tuple] = None, asset_type: Optional[tuple] = None,
                 dependencies: Optional[List[QueryType]] = tuple(), asset_type_excluded: Optional[tuple] = None):
    # Indicates that fn should be exported to plottool as a member function / pseudo-measure.
    # Set category to None for no restrictions, else provide a tuple of allowed values.
    def decorator(fn):
        assert asset_class is None or isinstance(asset_class, tuple)
        assert asset_type is None or isinstance(asset_type, tuple)
        assert asset_type_excluded is None or isinstance(asset_type_excluded, tuple)
        assert asset_type is None or asset_type_excluded is None

        fn.plot_measure = True
        fn.entity_type = EntityType.ASSET
        fn.asset_class = asset_class
        fn.asset_type = asset_type
        fn.asset_type_excluded = asset_type_excluded
        fn.dependencies = dependencies

        return fn

    return decorator


def plot_measure_entity(entity_type: EntityType, dependencies: Optional[Iterable[QueryType]] = tuple()):
    def decorator(fn):
        assert isinstance(entity_type, EntityType)
        if dependencies is not None:
            assert isinstance(dependencies, Iterable)
            assert all(isinstance(x, QueryType) for x in dependencies)

        fn.plot_measure_entity = True
        fn.entity_type = entity_type
        fn.dependencies = tuple(dependencies)  # immutable

        return fn

    return decorator


def requires_session(fn):
    fn.requires_session = True
    return fn


def plot_method(fn):
    # Indicates that fn should be exported to plottool as a method.
    fn.plot_method = True

    # Allows fn to accept and ignore real_time argument even if it is not defined in the signature
    @wraps(fn)
    def ignore_extra_argument(*args, **kwargs):
        for arg in ('real_time', 'interval', 'time_filter'):
            if arg not in inspect.signature(fn).parameters:
                kwargs.pop(arg, None)
        return fn(*args, **kwargs)

    return ignore_extra_argument


def log_return(logger: logging.Logger, message):
    def outer(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            response = fn(*args, **kwargs)
            logger.debug('%s: %s', message, response)
            return response

        return inner

    return outer


def get_df_with_retries(fetcher, start_date, end_date, exchange, retries=1):
    """
    Loads results from Data Service by calling fetcher function. Shifts query date range back by business days until
    result is not empty or retry limit reached. This is a fallback feature in case a data upload is late. Measure
    implementations should be written such that retries are usually not required.

    :param fetcher: a no-argument function runs a data query and returns a DataFrame
    :param start_date: initial start date for query
    :param end_date: initial end date for query
    :param exchange: exchange to use for holiday calendar
    :param retries: maximum number of retries
    :return: DataFrame
    """
    retries = max(retries, 0)
    while retries > -1:
        with DataContext(start_date, end_date):
            result = fetcher()
        if not result.empty:
            break
        kwargs = {'exchanges': [exchange]} if exchange else {}
        # no need to include any part of the previous date range since it's known to be empty
        end_date = RelativeDate('-1b', base_date=start_date).apply_rule(**kwargs)
        start_date = end_date
        retries -= 1
    return result
