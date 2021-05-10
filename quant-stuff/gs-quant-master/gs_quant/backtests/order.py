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

from abc import ABCMeta
from gs_quant.target.instrument import Instrument, Cash
from gs_quant.backtests.core import TimeWindow, ValuationFixingType
from gs_quant.backtests.data_handler import DataHandler
import numpy as np
import datetime as dt


class OrderBase(metaclass=ABCMeta):
    def __init__(self,
                 instrument: Instrument,
                 quantity: float,
                 generation_time: dt.datetime,
                 source: str):
        """
        Create an order
        :param instrument: an Instrument or Security to be traded
        :param quantity: quantity to be traded in instrument
        :param generation_time: the time when this order was generated
        :param source: the name of the entity that generated this order
        """
        self.instrument = instrument
        self.quantity = quantity
        self.generation_time = generation_time
        self.source = source

    def execution_end_time(self) -> dt.datetime:
        raise RuntimeError('The method execution_end_time is not implemented on OrderBase')

    def execution_price(self, data_handler: DataHandler) -> float:
        raise RuntimeError('The method execution_price is not implemented on OrderBase')

    def execution_quantity(self, data_handler: DataHandler) -> float:
        raise RuntimeError('The method execution_price is not implemented on OrderBase')

    def execution_notional(self, data_hander: DataHandler) -> float:
        return self.execution_price(data_hander) * self.execution_quantity(data_hander)

    def _short_name(self) -> str:
        raise RuntimeError('The method _short_name is not implemented on OrderBase')

    def to_dict(self, data_hander: DataHandler) -> dict:
        return {'Instrument': self.instrument.ric,
                'Type': self._short_name(),
                'Price': self.execution_price(data_hander),
                'Quantity': self.execution_quantity(data_hander)
                }


class OrderTWAP(OrderBase):
    def __init__(self,
                 instrument: Instrument,
                 quantity: float,
                 generation_time: dt.datetime,
                 source: str,
                 window: TimeWindow):
        super().__init__(instrument, quantity, generation_time, source)
        """
        Create a TWAP order
        :param window: TWAP window
        """
        self.window = window

    def execution_end_time(self) -> dt.datetime:
        return self.window.end

    def execution_price(self, data_handler: DataHandler) -> float:
        fixings = data_handler.get_data_range(self.window.start, self.window.end,
                                              self.instrument, ValuationFixingType.PRICE)
        return np.mean(fixings)

    def execution_quantity(self, data_handler: DataHandler) -> float:
        return self.quantity

    def _short_name(self) -> str:
        return 'TWAP {0}:{1}'.format(self.window.start, self.window.end)


class OrderMarketOnClose(OrderBase):
    def __init__(self,
                 instrument: Instrument,
                 quantity: float,
                 generation_time: dt.datetime,
                 execution_date: dt.date,
                 source: str):
        super().__init__(instrument, quantity, generation_time, source)
        self.execution_date = execution_date

    def execution_end_time(self) -> dt.datetime:
        return dt.datetime.combine(self.execution_date, dt.time(23, 0, 0))

    def execution_price(self, data_handler: DataHandler) -> float:
        return data_handler.get_data(self.execution_date, self.instrument, ValuationFixingType.PRICE)

    def execution_quantity(self, data_handler: DataHandler) -> float:
        return self.quantity

    def _short_name(self) -> str:
        return 'MOC'


class OrderCost(OrderBase):
    def __init__(self, currency: str, quantity: float, source: str, execution_time: dt.datetime):
        super().__init__(Cash(currency), quantity, generation_time=execution_time, source=source)
        """
        Create a cost order e.g. transaction or servicing cost
        :param execution_time: the time when the order is executed
        """
        self.execution_time = execution_time

    def execution_end_time(self) -> dt.datetime:
        return self.execution_time

    def execution_price(self, data_handler: DataHandler) -> float:
        return 0

    def execution_quantity(self, data_handler: DataHandler) -> float:
        return self.quantity

    def _short_name(self) -> str:
        return 'Cost'

    def to_dict(self, data_hander: DataHandler) -> dict:
        return {'Instrument': self.instrument.currency,
                'Type': self._short_name(),
                'Price': self.execution_price(data_hander),
                'Quantity': self.execution_quantity(data_hander)
                }


class OrderAtMarket(OrderBase):
    def __init__(self,
                 instrument: Instrument,
                 quantity: float,
                 generation_time: dt.datetime,
                 execution_datetime: dt.datetime,
                 source: str):
        super().__init__(instrument, quantity, generation_time, source)
        self.execution_datetime = execution_datetime

    def execution_end_time(self) -> dt.datetime:
        return self.execution_datetime

    def execution_price(self, data_handler: DataHandler) -> float:
        return data_handler.get_data(self.execution_datetime, self.instrument, ValuationFixingType.PRICE)

    def execution_quantity(self, data_handler: DataHandler) -> float:
        return self.quantity

    def _short_name(self) -> str:
        return 'Market'


class OrderTwapBTIC(OrderTWAP):
    def __init__(self,
                 instrument: Instrument,
                 quantity: float,
                 generation_time: dt.datetime,
                 source: str,
                 window: TimeWindow,
                 btic_instrument: Instrument):
        super().__init__(instrument, quantity, generation_time, source, window)
        """
        Create a TWAP order
        :param window: TWAP window
        """
        self.btic_instrument = btic_instrument

    def execution_price(self, data_handler: DataHandler) -> float:
        btic_fixings = data_handler.get_data_range(self.window.start, self.window.end,
                                                   self.btic_instrument, ValuationFixingType.PRICE)
        btic_twap = np.mean(btic_fixings)
        close = data_handler.get_data(self.window.end.date(), self.instrument, ValuationFixingType.PRICE)

        return close + btic_twap

    def _short_name(self) -> str:
        return 'TwapBTIC'
