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

from typing import Optional

import pandas as pd
from pandas import Series

from gs_quant.analytics.core.processor import BaseProcessor, DataCoordinateOrProcessor, DateOrDatetimeOrRDate
from gs_quant.analytics.core.processor_result import ProcessorResult


class LastProcessor(BaseProcessor):

    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None):
        """ LastProcessor returns the last value of the series

        :param a: DataCoordinate or BaseProcessor for the first coordinate
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        """
        super().__init__()
        # coordinates
        self.children['a'] = a

        # datetime
        self.start = start
        self.end = end

    def process(self) -> None:
        """ Calculate the result and store it as the processor value """
        a_data = self.children_data.get('a')
        if isinstance(a_data, ProcessorResult):
            if a_data.success and isinstance(a_data.data, Series):
                self.value = ProcessorResult(True, pd.Series(a_data.data[-1:]))

    def get_plot_expression(self):
        pass


class MinProcessor(BaseProcessor):

    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None):
        """ MinProcessor returns the minimum value of the series

        :param a: DataCoordinate or BaseProcessor for the coordinate
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        """
        super().__init__()
        # coordinates
        self.children['a'] = a

        # datetime
        self.start = start
        self.end = end

    def process(self) -> None:
        """ Calculate the result and store it as the processor value """
        a = self.children_data.get('a')
        if isinstance(a, ProcessorResult):
            if a.success and isinstance(a.data, Series):
                self.value = ProcessorResult(True, pd.Series(min(a.data)))
            else:
                self.value = ProcessorResult(False, "Processor does not data series yet")
        else:
            self.value = ProcessorResult(False, "Processor does not have series yet")

    def get_plot_expression(self):
        pass


class MaxProcessor(BaseProcessor):

    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None):
        """ MaxProcessor returns the maximum value of the series

        :param a: DataCoordinate or BaseProcessor for the coordinate
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        """
        super().__init__()
        # coordinates
        self.children['a'] = a

        # datetime
        self.start = start
        self.end = end

    def process(self) -> None:
        """ Calculate the result and store it as the processor value """
        a = self.children_data.get('a')
        if isinstance(a, ProcessorResult):
            if a.success and isinstance(a.data, Series):
                self.value = ProcessorResult(True, pd.Series(max(a.data)))
            else:
                self.value = ProcessorResult(False, "Processor does not have data series yet")
        else:
            self.value = ProcessorResult(False, "Processor does not have series yet")

    def get_plot_expression(self):
        pass


class AppendProcessor(BaseProcessor):
    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 b: DataCoordinateOrProcessor,
                 *,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None):
        """ AppendProcessor appends both a and b data series into one series

        :param a: DataCoordinate or BaseProcessor for the first series
        :param b: DataCoordinate or BaseProcessor for the second series
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        """
        super().__init__()
        # coordinates
        self.children['a'] = a
        self.children['b'] = b

        # datetime
        self.start = start
        self.end = end

    def process(self) -> None:
        a_data = self.children_data.get('a')
        b_data = self.children_data.get('b')
        if isinstance(a_data, ProcessorResult) and isinstance(b_data, ProcessorResult):
            if a_data.success and b_data.success:
                result = a_data.data.append(b_data.data)
                self.value = ProcessorResult(True, result)
            else:
                self.value = ProcessorResult(False, "Processor does not have A and B data yet")
        else:
            self.value = ProcessorResult(False, "Processor does not have A and B data yet")

    def get_plot_expression(self):
        pass


class AdditionProcessor(BaseProcessor):
    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 *,
                 b: Optional[DataCoordinateOrProcessor] = None,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None,
                 addend: Optional[float] = None):
        """ AdditionProcessor adds two series or an addend to a series


        :param a: DataCoordinate or BaseProcessor for the first series
        :param b: DataCoordinate or BaseProcessor for the second series to add to the first
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        :param addend: number to add to all values in the series
        """
        super().__init__()
        # coordinates
        self.children['a'] = a
        self.children['b'] = b
        # datetime
        self.start = start
        self.end = end

        self.addend = addend

    def process(self):
        a_data = self.children_data.get('a')
        if isinstance(a_data, ProcessorResult):
            if not a_data.success:
                self.value = a_data
                return
            if self.addend:
                value = a_data.data.add(self.addend)
                self.value = ProcessorResult(True, value)
                return
            b_data = self.children_data.get('b')
            if isinstance(b_data, ProcessorResult):
                if b_data.success:
                    value = a_data.data.add(b_data.data)
                    self.value = ProcessorResult(True, value)
                else:
                    self.value = ProcessorResult(True, b_data.data)

    def get_plot_expression(self):
        pass


class SubtractionProcessor(BaseProcessor):
    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 b: Optional[DataCoordinateOrProcessor] = None,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None,
                 subtrahend: Optional[float] = None):
        """ SubtractionProcessor subtract two series or a subtrahend to a series


        :param a: DataCoordinate or BaseProcessor for the first series
        :param b: DataCoordinate or BaseProcessor for the second series to subtract to the first
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        :param subtrahend: number to subtract from all values in the series
        """
        super().__init__()
        # coordinates
        self.children['a'] = a
        self.children['b'] = b
        # datetime
        self.start = start
        self.end = end

        self.subtrahend = subtrahend

    def process(self):
        a_data = self.children_data.get('a')
        if isinstance(a_data, ProcessorResult):
            if not a_data.success:
                self.value = a_data
                return
            if self.subtrahend:
                value = a_data.data.sub(self.subtrahend)
                self.value = ProcessorResult(True, value)
                return
            b_data = self.children_data.get('b')
            if isinstance(b_data, ProcessorResult):
                if b_data.success:
                    value = a_data.data.sub(b_data.data)
                    self.value = ProcessorResult(True, value)
                else:
                    self.value = b_data

    def get_plot_expression(self):
        pass


class MultiplicationProcessor(BaseProcessor):
    """ Multiply scalar or series together """

    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 b: Optional[DataCoordinateOrProcessor] = None,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None,
                 factor: Optional[float] = None):
        """ MultiplicationProcessor multiply two series or a factor to a series


        :param a: DataCoordinate or BaseProcessor for the first series
        :param b: DataCoordinate or BaseProcessor for the second series to multiply to the first
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        :param factor: number to multiply all values in the series
        """
        super().__init__()
        # coordinates
        self.children['a'] = a
        self.children['b'] = b
        # datetime
        self.start = start
        self.end = end

        self.factor = factor

    def process(self):
        a_data = self.children_data.get('a')
        if isinstance(a_data, ProcessorResult):
            if not a_data.success:
                self.value = a_data
                return
            if self.factor:
                value = a_data.data.mul(self.factor)
                self.value = ProcessorResult(True, value)
                return
            b_data = self.children_data.get('b')
            if isinstance(b_data, ProcessorResult):
                if b_data.success:
                    value = a_data.data.mul(b_data.data)
                    self.value = ProcessorResult(True, value)
                else:
                    self.value = b_data

    def get_plot_expression(self):
        pass


class DivisionProcessor(BaseProcessor):
    def __init__(self,
                 a: DataCoordinateOrProcessor,
                 b: Optional[DataCoordinateOrProcessor] = None,
                 start: Optional[DateOrDatetimeOrRDate] = None,
                 end: Optional[DateOrDatetimeOrRDate] = None,
                 dividend: Optional[float] = None):
        """ DivisionProcessor divides two series or divides a dividend to a series


        :param a: DataCoordinate or BaseProcessor for the first series
        :param b: DataCoordinate or BaseProcessor for the second series to multiply to the first
        :param start: start date or time used in the underlying data query
        :param end: end date or time used in the underlying data query
        :param dividend: number to divide all values in the series
        """
        super().__init__()
        # coordinates
        self.children['a'] = a
        self.children['b'] = b
        # datetime
        self.start = start
        self.end = end

        self.dividend = dividend

    def process(self):
        a_data = self.children_data.get('a')
        if isinstance(a_data, ProcessorResult):
            if not a_data.success:
                self.value = a_data
                return
            if self.dividend:
                value = a_data.data.div(self.dividend)
                self.value = ProcessorResult(True, value)
                return
            b_data = self.children_data.get('b')
            if isinstance(b_data, ProcessorResult):
                if b_data.success:
                    value = a_data.data.div(b_data.data)
                    self.value = ProcessorResult(True, value)
                else:
                    self.value = b_data

    def get_plot_expression(self):
        pass
