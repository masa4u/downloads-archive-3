"""
Copyright 2020 Goldman Sachs.
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

from dateutil.relativedelta import relativedelta as rdelta
from functools import reduce

from gs_quant.timeseries.helper import _create_enum
from .statistics import *
from ..api.gs.assets import GsAssetApi
from ..api.gs.data import GsDataApi

RebalFreq = _create_enum('RebalFreq', ['Daily', 'Monthly'])
ReturnType = _create_enum('ReturnType', ['excess_return'])


@plot_function
def basket_series(
    series: list,
    weights: list,
    costs: list = None,
    rebal_freq: RebalFreq = RebalFreq.DAILY,
    return_type: ReturnType = ReturnType.EXCESS_RETURN,
) -> pd.Series:
    """
    Calculates a basket return series.

    :param series: list of time series of instrument prices
    :param weights: list of weights
    :param costs: list of execution costs in decimal; defaults to costs of 0
    :param rebal_freq: rebalancing frequency - Daily or Monthly
    :param return_type: return type of underlying instruments - only excess return is supported
    :return: time series of the resulting basket

    **Usage**

    Calculates a basket return series.

    **Examples**

    Generate price series and combine them in a basket (weights 70%/30%) which rebalances monthly and assumes
    execution costs 5bps and 10bps each time the constituents are traded.

    >>> prices1 = generate_series(100)
    >>> prices2 = generate_series(100)
    >>> mybasket = basket_series([prices1, prices2], [0.7, 0.3], [0.0005, 0.001], monthly)

    **See also**

    :func:`prices`
    """

    num_assets = len(series)
    costs = costs or [0] * num_assets

    if not all(isinstance(x, pd.Series) for x in series):
        raise MqTypeError("expected a list of series")

    if len(weights) != num_assets or len(weights) != len(costs):
        raise MqValueError("series, weights, and cost lists must have the same length")

    # For all inputs which are Pandas series, get the intersection of their calendars
    cal = pd.DatetimeIndex(
        reduce(
            np.intersect1d,
            (
                curve.index
                for curve in series + weights + costs
                if isinstance(curve, pd.Series)
            ),
        )
    )

    # Reindex inputs and convert to pandas dataframes
    series = pd.concat([curve.reindex(cal) for curve in series], axis=1)
    weights = pd.concat([pd.Series(w, index=cal) for w in weights], axis=1)
    costs = pd.concat([pd.Series(c, index=cal) for c in costs], axis=1)

    if rebal_freq == RebalFreq.DAILY:
        rebal_dates = cal
    else:
        # Get hypothetical monthly rebalances
        num_rebals = (cal[-1].year - cal[0].year) * 12 + cal[-1].month - cal[0].month
        rebal_dates = [cal[0] + i * rdelta(months=1) for i in range(num_rebals + 1)]
        # Convert these to actual calendar days
        rebal_dates = [d for d in rebal_dates if d < max(cal)]
        rebal_dates = [min(cal[cal >= date]) for date in rebal_dates]

    # Create Units dataframe
    units = pd.DataFrame(index=cal, columns=series.columns)
    output = pd.Series(dtype='float64', index=cal)

    # Initialize backtest
    output.values[0] = 100
    units.values[0, ] = (
        output.values[0] * weights.values[0, ] / series.values[0, ]
    )

    # Run backtest
    prev_rebal = 0
    for i, date in enumerate(cal[1:], 1):
        # Update performance
        output.values[i] = output.values[i - 1] + np.dot(
            units.values[i - 1, ], series.values[i, ] - series.values[i - 1, ]
        )

        # Rebalance on rebal_dates
        if date in rebal_dates:
            # Compute costs
            actual_weights = (
                weights.values[prev_rebal, ] *
                (series.values[i, ] / series.values[prev_rebal, ]) *
                (output.values[prev_rebal] / output.values[i])
            )
            output.values[i] -= (
                np.dot(costs.values[i, ], np.abs(weights.values[i, ] - actual_weights)) *
                output.values[i]
            )

            # Rebalance
            units.values[i, ] = (
                output.values[i] * weights.values[i, ] / series.values[i, ]
            )
            prev_rebal = i
        else:
            units.values[i, ] = units.values[
                i - 1,
            ]

    return output


class Basket:
    """
    Construct a basket of stocks

    :param stocks: list of stock bloomberg ids
    :param weights: list of weights
    :param rebal_freq: rebalancing frequency - Daily or Monthly

    """
    def __init__(self, stocks: list, weights: list, rebal_freq: RebalFreq = RebalFreq.DAILY):
        if len(stocks) != len(weights):
            raise MqValueError("stocks and weights must have the same length")

        self.bbids = stocks
        self.rebal_freq = rebal_freq
        self.weights = weights
        self.__marquee_ids = None

    def get_marquee_ids(self):
        if self.__marquee_ids is None:
            assets = GsAssetApi.get_many_assets_data(bbid=self.bbids, fields=('id', ))
            self.__marquee_ids = [a['id'] for a in assets]

            if len(self.__marquee_ids) != len(self.bbids):
                raise MqValueError('Unable to find all stocks')

        return self.__marquee_ids

    @requires_session
    @plot_method
    def price(self, *, real_time: bool = False) -> pd.Series:
        """
        Weighted average price

        :param real_time: whether to retrieve intraday data instead of EOD
        :return: time series of the average price
        """
        if real_time:
            raise NotImplementedError('real-time basket price not implemented')

        q = GsDataApi.build_market_data_query(self.get_marquee_ids(), QueryType.SPOT)
        df = GsDataApi.get_market_data(q)

        grouped = df.groupby('assetId')
        spot_series = [grouped.get_group(mqid)['spot'] for mqid in self.get_marquee_ids()]
        return basket_series(spot_series, self.weights, rebal_freq=self.rebal_freq)
