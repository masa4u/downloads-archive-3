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

from typing import Tuple

from gs_quant.backtests.triggers import *
from gs_quant.backtests.generic_engine import GenericEngine
from gs_quant.backtests.predefined_asset_engine import PredefinedAssetEngine
from gs_quant.backtests.equity_vol_engine import EquityVolEngine
from gs_quant.base import Priceable


backtest_engines = [GenericEngine(), PredefinedAssetEngine(), EquityVolEngine()]


class Strategy(object):
    """
    A strategy object on which one may run a backtest
    """

    def __init__(self, initial_portfolio: Optional[Tuple[Priceable, ...]], triggers: Union[Trigger, Iterable[Trigger]]):
        self._initial_portfolio = make_list(initial_portfolio)
        self._triggers = make_list(triggers)

    @property
    def triggers(self):
        return self._triggers

    @property
    def initial_portfolio(self):
        return self._initial_portfolio

    @property
    def risks(self):
        risk_list = []
        for t in self._triggers:
            risk_list += t.risks if t.risks is not None else []
        return risk_list

    def get_available_engines(self):
        return [engine for engine in backtest_engines if engine.supports_strategy(self)]
