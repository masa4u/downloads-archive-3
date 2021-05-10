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

import datetime as dt
import json
import logging
import pandas as pd

from copy import deepcopy
from enum import Enum
from functools import wraps
from pydash import get, has, set_
from typing import Dict, List, Optional

from gs_quant.api.gs.assets import GsAsset, GsAssetApi
from gs_quant.api.gs.data import GsDataApi
from gs_quant.api.gs.indices import GsIndexApi
from gs_quant.api.gs.reports import GsReportApi
from gs_quant.api.gs.users import GsUsersApi
from gs_quant.common import DateLimit, PositionType
from gs_quant.entities.entity import EntityType, PositionedEntity
from gs_quant.errors import MqError, MqValueError
from gs_quant.json_encoder import JSONEncoder
from gs_quant.markets.indices_utils import *
from gs_quant.markets.position_set import PositionSet
from gs_quant.markets.securities import Asset, AssetType as SecAssetType
from gs_quant.session import GsSession
from gs_quant.target.data import DataQuery
from gs_quant.target.indices import *
from gs_quant.target.reports import Report, ReportStatus


_logger = logging.getLogger(__name__)


class ErrorMessage(Enum):
    NON_ADMIN = 'You are not permitted to perform this action on this basket. Please make sure \
        the basket owner has entitled your application properly if you believe this is a mistake'
    NON_INTERNAL = 'You are not permitted to access this basket setting.'
    UNINITIALIZED = 'Basket class object must be initialized using one of an existing basket\'s \
        identifiers to perform this action'
    UNMODIFIABLE = 'This property can not be modified since the basket has already been created'


def _error(*error_msgs):
    def _outer(fn):
        @wraps(fn)
        def _inner(self, *args, **kwargs):
            if has(self, '_Basket__error_messages'):
                for error_msg in error_msgs:
                    if error_msg in self._Basket__error_messages:
                        raise MqError(error_msg.value)
            return fn(self, *args, **kwargs)
        return _inner
    return _outer


class Basket(Asset, PositionedEntity):
    """
    Basket which tracks an evolving portfolio of securities, and can be traded through cash or derivatives markets
    """
    def __init__(self, identifier: str = None, gs_asset: GsAsset = None, **kwargs):
        user_tokens = get(GsUsersApi.get_current_user_info(), 'tokens', [])
        user_is_internal = 'internal' in user_tokens
        if identifier:
            gs_asset = self.__get_gs_asset(identifier)
        if gs_asset:
            if gs_asset.type.value not in BasketType.to_list():
                raise MqValueError(f'Failed to initialize. Asset {gs_asset.id} is not a basket')
            self.__id = gs_asset.id
            asset_entity: Dict = json.loads(json.dumps(gs_asset.as_dict(), cls=JSONEncoder))
            Asset.__init__(self, gs_asset.id, gs_asset.asset_class, gs_asset.name,
                           exchange=gs_asset.exchange, currency=gs_asset.currency, entity=asset_entity)
            PositionedEntity.__init__(self, gs_asset.id, EntityType.ASSET)
            user_is_admin = any(token in user_tokens for token in get(gs_asset.entitlements, 'admin', []))
            self.__populate_current_attributes_for_existing_basket(gs_asset)
            self.__set_error_messages(user_is_admin, user_is_internal, True)
            self.__populate_api_attrs = True
        else:
            self.__set_error_messages(True, user_is_internal, False)
            self.__populate_default_attributes_for_new_basket(**kwargs)
            self.__populate_api_attrs = False

    def get_details(self) -> pd.DataFrame:
        """
        Get basket details

        :return: dataframe containing current basket properties

        **Usage**

        Get basket's current state

        **Examples**

        Get basket details:

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_details()
        """
        props = list(CustomBasketsPricingParameters.properties().union(PublishParameters.properties(),
                     CustomBasketsCreateInputs.properties()))
        props = sorted(props)
        details = [{'name': k, 'value': get(self, k)} for k in props if has(self, k)]
        return pd.DataFrame(details)

    def create(self) -> Dict:
        """
        Create a new custom basket in Marquee

        :return: dictionary containing asset id and report id

        **Usage**

        Create a new custom basket in Marquee

        **See also**

        :func:`get_details` :func:`poll_status` :func:`update`

        """
        inputs, pricing, publish = {}, {}, {}
        for prop in CustomBasketsCreateInputs.properties():
            set_(inputs, prop, get(self, prop))
        for prop in CustomBasketsPricingParameters.properties():
            set_(pricing, prop, get(self, prop))
        for prop in PublishParameters.properties():
            set_(publish, prop, get(self, prop))
        set_(inputs, 'position_set', self.position_set.to_target(common=False))
        set_(inputs, 'pricing_parameters', CustomBasketsPricingParameters(**pricing))
        set_(inputs, 'publish_parameters', PublishParameters(**publish))
        create_inputs = CustomBasketsCreateInputs(**inputs)

        response = GsIndexApi.create(create_inputs)
        gs_asset = GsAssetApi.get_asset(response.asset_id)
        self.__latest_create_report = GsReportApi.get_report(response.report_id)
        self.__init__(gs_asset=gs_asset)
        return response.as_dict()

    @_error(ErrorMessage.UNINITIALIZED)
    def clone(self):
        """
        Retrieve a clone of an existing basket

        :return: New basket instance with position set identical to current basket

        **Usage**

        Clone an existing basket's position set in a new basket instance prior to creation

        **Examples**

        Clone current basket:

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> parent_basket = Basket("GSMBXXXX")
        >>> clone = parent_basket.clone()

        **See also**

        :func:`create`
        """
        self.__finish_populating_attributes_for_existing_basket()
        position_set = deepcopy(self.position_set)
        return Basket(position_set=position_set, clone_parent_id=self.id, parent_basket=self.ticker)

    @_error(ErrorMessage.UNINITIALIZED, ErrorMessage.NON_ADMIN)
    def update(self) -> Dict:
        """
        Update your custom basket

        :return: dictionary containing asset id and report id

        **Usage**

        Make updates to your basket's metadata, pricing options, publishing options, or composition

        **See also**

        :func:`get_details` :func:`poll_status` :func:`create`

        """
        self.__finish_populating_attributes_for_existing_basket()
        edit_inputs, rebal_inputs = self.__get_updates()
        if edit_inputs is None and rebal_inputs is None:
            raise MqValueError('Update failed: Nothing on the basket was changed')
        elif edit_inputs is not None and rebal_inputs is None:
            response = GsIndexApi.edit(self.id, edit_inputs)
        elif rebal_inputs is not None and edit_inputs is None:
            response = GsIndexApi.rebalance(self.id, rebal_inputs)
        else:
            response = self.__edit_and_rebalance(edit_inputs, rebal_inputs)
        gs_asset = GsAssetApi.get_asset(self.id)
        self.__latest_create_report = GsReportApi.get_report(response.report_id)
        self.__error_messages.remove(ErrorMessage.UNMODIFIABLE)
        self.__init__(gs_asset=gs_asset)
        return response.as_dict()

    @_error(ErrorMessage.UNINITIALIZED, ErrorMessage.NON_ADMIN)
    def upload_position_history(self, position_sets: List[PositionSet]) -> Dict:
        """
        Upload basket composition history

        :param position_sets: list of dated position sets
        :return: dictionary containing asset id and report id

        **Usage**

        Upload your basket's historical composition after it's been created

        **Examples**

        Upload composition history from a list of identifiers:

        >>> from datetime import date
        >>> from gs_quant.markets.baskets import Basket
        >>> from gs_quant.markets.position_set import PositionSet
        >>>
        >>> first_position_set = PositionSet.from_list(['BBID1', 'BBID2'], date(2020, 1, 1))
        >>> second_position_set = PositionSet.from_list(['BBID1','BBID2', 'BBID3'], date(2021, 1, 1))
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.upload_position_history([first_position_set, second_position_set])

        **See also**

        :class:`PositionSet`
        """
        if self.default_backcast:
            raise MqValueError('Unable to upload position history: option must be set during basket creation')
        historical_position_sets = []
        for position_set in position_sets:
            positions = [IndicesPositionInput(p.asset_id, p.weight) for p in position_set.positions]
            historical_position_sets.append(IndicesPositionSet(tuple(positions), position_set.date))
        response = GsIndexApi.backcast(CustomBasketsBackcastInputs(tuple(historical_position_sets)))
        return response.as_dict()

    @_error(ErrorMessage.UNINITIALIZED)
    def poll_status(self, timeout: int = 600, step: int = 30) -> ReportStatus:
        """
        Polls the status of the basket's most recent create/edit/rebalance report

        :param timeout: how many seconds you'd like to poll for (default is 600 sec)
        :param step: how frequently you'd like to check the report's status (default is every 30 sec)
        :return: Report status

        **Usage**

        Poll the status of a newly created or updated basket

        **Examples**

        Poll most recent create/update report status:

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.poll_status(timeout=120, step=20)

        **See also**

        :func:`create` :func:`update`
        """
        report = get(self, '__latest_create_report', self.__get_latest_create_report())
        report_id = get(report, 'id')
        return self.poll_report(report_id, timeout, step)

    @_error(ErrorMessage.UNINITIALIZED)
    def get_latest_rebalance_data(self) -> Dict:
        """
        Retrieve the most recent rebalance data for a basket

        **Usage**

        Retrieve the most recent rebalance data for a basket

        **Examples**

        Retrieve the most recent rebalance data for a basket

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_latest_rebalance_data()

        **See also**

        :func:`get_latest_rebalance_date`
        """
        return GsIndexApi.last_rebalance_data(self.id)

    @_error(ErrorMessage.UNINITIALIZED)
    def get_latest_rebalance_date(self) -> dt.date:
        """
        Retrieve the most recent rebalance date for a basket

        :return: dictionary

        **Usage**

        Retrieve the most recent rebalance date for a basket

        **Examples**

        Retrieve the most recent rebalance date for a basket

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_latest_rebalance_date()

        **See also**

        :func:`get_latest_rebalance_data`
        """
        last_rebalance = GsIndexApi.last_rebalance_data(self.id)
        return dt.datetime.strptime(last_rebalance['date'], '%Y-%m-%d').date()

    @_error(ErrorMessage.UNINITIALIZED)
    def get_rebalance_approval_status(self) -> str:
        """
        Retrieve the most recent rebalance submission's approval status

        :return: current approval status

        **Usage**

        Retrieve the most recent rebalance submission's approval status

        **Examples**

        Retrieve the most recent rebalance submission's approval status

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_rebalance_approval_status()

        **See also**

        :func:`cancel_rebalance` :func:`poll_report`
        """
        last_approval = GsIndexApi.last_rebalance_approval(self.id)
        return get(last_approval, 'status')

    @_error(ErrorMessage.NON_ADMIN)
    def cancel_rebalance(self) -> Dict:
        """
        Cancel the most recent rebalance submission

        **Usage**

        Cancel the basket's most recent rebalance submission if it has not yet been approved

        **Examples**

        Cancel the basket's most recent rebalance submission

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.cancel_rebalance()

        **See also**

        :func:`get_rebalance_approval_status` :func:`update`
        """
        return GsIndexApi.cancel_rebalance(self.id)

    @_error(ErrorMessage.UNINITIALIZED)
    def get_corporate_actions(self,
                              start: dt.date = DateLimit.LOW_LIMIT.value,
                              end: dt.date = dt.date.today() + dt.timedelta(days=10),
                              ca_type: [CorporateActionType] = CorporateActionType.to_list()) -> pd.DataFrame:
        """
        Retrieve corporate actions for a basket across a date range

        :param start: start date (default minimum date value)
        :param end: end date (default is maximum date value)
        :param ca_type: list of corporate action types (default is all)
        :return: dataframe with corporate actions information

        **Usage**

        Retrieve corporate actions for a basket across a date range

        **Examples**

        Retrieve historical acquisition corporate actions for a basket

        >>> from gs_quant.markets.baskets import Basket
        >>> from gs_quant.markets.indices_utils import CorporateActionType
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_corporate_actions(ca_type=[CorporateActionType.ACQUISITION])

        **See also**

        :func:`get_fundamentals`
        """
        where = dict(assetId=self.id, corporateActionType=ca_type)
        query = DataQuery(where=where, start_date=start, end_date=end)
        response = GsDataApi.query_data(query=query, dataset_id=IndicesDatasets.CORPORATE_ACTIONS.value)
        return pd.DataFrame(response)

    @_error(ErrorMessage.UNINITIALIZED)
    def get_fundamentals(self,
                         start: dt.date = DateLimit.LOW_LIMIT.value,
                         end: dt.date = dt.date.today(),
                         period: FundamentalMetricPeriod = FundamentalMetricPeriod.ONE_YEAR.value,
                         direction: FundamentalMetricPeriodDirection = FundamentalMetricPeriodDirection.FORWARD.value,
                         metrics: [FundamentalsMetrics] = FundamentalsMetrics.to_list()) -> pd.DataFrame:
        """
        Retrieve fundamentals data for a basket across a date range

        :param start: start date (default minimum date value)
        :param end: end date (default is today)
        :param period: period for the relevant metric (default is 1y)
        :param direction: direction of the outlook period (default is forward)
        :param metrics: list of fundamentals metrics (default is all)
        :return: dataframe with fundamentals information

        **Usage**

        Retrieve fundamentals data for a basket across a date range

        **Examples**

        Retrieve historical dividend yield data for a basket

        >>> from gs_quant.markets.baskets import Basket
        >>> from gs_quant.markets.indices_utils import FundamentalsMetrics
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_corporate_actions(metrics=[FundamentalsMetrics.DIVIDEND_YIELD])

        **See also**

        :func:`get_corporate_actions`
        """
        where = dict(assetId=self.id, period=period, periodDirection=direction, metric=metrics)
        query = DataQuery(where=where, start_date=start, end_date=end)
        response = GsDataApi.query_data(query=query, dataset_id=IndicesDatasets.BASKET_FUNDAMENTALS.value)
        return pd.DataFrame(response)

    @_error(ErrorMessage.UNINITIALIZED)
    def get_live_date(self) -> Optional[dt.date]:
        """
        Retrieve basket's live date

        **Usage**

        Retrieve basket's live date

        **Examples**

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_live_date()
        """
        return self.__live_date

    @_error(ErrorMessage.UNINITIALIZED)
    def get_type(self) -> Optional[SecAssetType]:
        """
        Retrieve basket type

        **Usage**

        Retrieve basket type

        **Examples**

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_type()
        """
        return SecAssetType[self.__gs_asset_type.name.upper()]

    @_error(ErrorMessage.UNINITIALIZED)
    def get_url(self) -> str:
        """
        Retrieve url to basket's product page in Marquee

        **Usage**

        Retrieve url to basket's product page in Marquee

        **Examples**

        >>> from gs_quant.markets.baskets import Basket
        >>>
        >>> basket = Basket("GSMBXXXX")
        >>> basket.get_url()
        """
        env = '-dev' if 'dev' in get(GsSession, 'current.domain', '') else ''
        env = '-qa' if 'qa' in get(GsSession, 'current.domain', '') else env
        return f'https://marquee{env}.gs.com/s/products/{self.id}/summary'

    @property
    def allow_ca_restricted_assets(self) -> Optional[bool]:
        """ Allow basket to have constituents that will not be corporate action adjusted in the future """
        return self.__allow_ca_restricted_assets

    @allow_ca_restricted_assets.setter
    @_error(ErrorMessage.NON_ADMIN)
    def allow_ca_restricted_assets(self, value: bool):
        self.__allow_ca_restricted_assets = value

    @property
    def allow_limited_access_assets(self) -> Optional[bool]:
        """ Allow basket to have constituents that GS has limited access to """
        return self.__allow_limited_access_assets

    @allow_limited_access_assets.setter
    @_error(ErrorMessage.NON_ADMIN)
    def allow_limited_access_assets(self, value: bool):
        self.__allow_limited_access_assets = value

    @property
    def clone_parent_id(self) -> Optional[str]:
        """ Marquee Id of the source basket, in case basket composition is sourced from another marquee basket """
        return self.__clone_parent_id

    @property
    def currency(self) -> Optional[IndicesCurrency]:
        """ Denomination of the basket """
        return self.__currency

    @currency.setter
    @_error(ErrorMessage.UNMODIFIABLE)
    def currency(self, value: IndicesCurrency):
        self.__currency = value

    @property
    def default_backcast(self) -> Optional[bool]:
        """ If basket should be backcasted using the current composition """
        return self.__default_backcast

    @default_backcast.setter
    @_error(ErrorMessage.UNMODIFIABLE)
    def default_backcast(self, value: bool):
        self.__default_backcast = value

    @property
    def description(self) -> Optional[str]:
        """ Free text description of basket """
        return self.__description

    @description.setter
    @_error(ErrorMessage.NON_ADMIN)
    def description(self, value: str):
        self.__description = value

    @property
    def divisor(self) -> Optional[float]:
        """ Divisor to be applied to the overall position set """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__divisor

    @divisor.setter
    @_error(ErrorMessage.NON_ADMIN)
    def divisor(self, value: float):
        self.__finish_populating_attributes_for_existing_basket()
        self.__initial_price = None
        self.__divisor = value

    @property
    @_error(ErrorMessage.NON_INTERNAL)
    def flagship(self) -> Optional[bool]:
        """ If the basket is flagship (internal only) """
        return self.__flagship

    @flagship.setter
    @_error(ErrorMessage.NON_INTERNAL)
    def flagship(self, value: bool):
        self.__flagship = value

    @property
    def hedge_id(self) -> Optional[str]:
        """ Marquee Id of the source hedge, in case current basket composition is sourced from marquee hedge """
        return self.__hedge_id

    @property
    def include_price_history(self) -> Optional[bool]:
        """ Include full price history when publishing to Bloomberg """
        return self.__include_price_history

    @include_price_history.setter
    @_error(ErrorMessage.NON_ADMIN)
    def include_price_history(self, value: bool):
        self.__include_price_history = value

    @property
    def initial_price(self) -> Optional[float]:
        """ Initial price the basket it should start ticking at """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__initial_price

    @initial_price.setter
    @_error(ErrorMessage.NON_ADMIN)
    def initial_price(self, value: float):
        self.__finish_populating_attributes_for_existing_basket()
        self.__divisor = None
        self.__initial_price = value

    @property
    def name(self) -> Optional[str]:
        """ Display name of the basket """
        return self.__name

    @name.setter
    @_error(ErrorMessage.NON_ADMIN)
    def name(self, value: str):
        self.__name = value

    @property
    def parent_basket(self) -> Optional[str]:
        """ Ticker of the source basket, in case current basket composition is sourced from another marquee basket """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__parent_basket

    @parent_basket.setter
    @_error(ErrorMessage.UNMODIFIABLE)
    def parent_basket(self, value: str):
        self.__finish_populating_attributes_for_existing_basket()
        self.__clone_parent_id = get(self.__get_gs_asset(value), 'id')
        self.__parent_basket = value

    @property
    def position_set(self) -> Optional[PositionSet]:
        """ Information of constituents associated with the basket """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__position_set

    @position_set.setter
    @_error(ErrorMessage.NON_ADMIN)
    def position_set(self, value: PositionSet):
        self.__finish_populating_attributes_for_existing_basket()
        self.__position_set = value

    @property
    def publish_to_bloomberg(self) -> Optional[bool]:
        """ If the basket should be published to Bloomberg """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__publish_to_bloomberg

    @publish_to_bloomberg.setter
    @_error(ErrorMessage.NON_ADMIN)
    def publish_to_bloomberg(self, value: bool):
        self.__finish_populating_attributes_for_existing_basket()
        self.__publish_to_bloomberg = value

    @property
    def publish_to_factset(self) -> Optional[bool]:
        """ If the basket should be published to Factset """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__publish_to_factset

    @publish_to_factset.setter
    @_error(ErrorMessage.NON_ADMIN)
    def publish_to_factset(self, value: bool):
        self.__finish_populating_attributes_for_existing_basket()
        self.__publish_to_factset = value

    @property
    def publish_to_reuters(self) -> Optional[bool]:
        """ If the basket should be published to Reuters """
        self.__finish_populating_attributes_for_existing_basket()
        return self.__publish_to_reuters

    @publish_to_reuters.setter
    @_error(ErrorMessage.NON_ADMIN)
    def publish_to_reuters(self, value: bool):
        self.__finish_populating_attributes_for_existing_basket()
        self.__publish_to_reuters = value

    @property
    def return_type(self) -> Optional[ReturnType]:
        """ Determines the index calculation methodology with respect to dividend reinvestment """
        return self.__return_type

    @return_type.setter
    @_error(ErrorMessage.NON_ADMIN)
    def return_type(self, value: ReturnType):
        self.__return_type = value

    @property
    def reweight(self) -> Optional[bool]:
        """ To reweight positions if input weights don't add up to 1 """
        return self.__reweight

    @reweight.setter
    @_error(ErrorMessage.NON_ADMIN)
    def reweight(self, value: bool):
        self.__reweight = value

    @property
    def target_notional(self) -> Optional[float]:
        """ Target notional for the position set """
        return self.__target_notional

    @target_notional.setter
    @_error(ErrorMessage.NON_ADMIN)
    def target_notional(self, value: float):
        self.__target_notional = value

    @property
    def ticker(self) -> Optional[str]:
        """ Associated 8-character basket identifier """
        return self.__ticker

    @ticker.setter
    @_error(ErrorMessage.UNMODIFIABLE)
    def ticker(self, value: str):
        self.__validate_ticker(value)
        self.__ticker = value

    @property
    def weighting_strategy(self) -> Optional[WeightingStrategy]:
        """ Strategy used to price the position set """
        return self.__weighting_strategy

    @weighting_strategy.setter
    @_error(ErrorMessage.NON_ADMIN)
    def weighting_strategy(self, value: WeightingStrategy):
        self.__weighting_strategy = value

    def __edit_and_rebalance(self, edit_inputs: CustomBasketsEditInputs,
                             rebal_inputs: CustomBasketsRebalanceInputs) -> CustomBasketsResponse:
        """ If updates require edit and rebalance, rebal will not be scheduled until/if edit report succeeds """
        _logger.info('Current update request requires multiple reports. Your rebalance request will be submitted \
                      once the edit report has completed. Submitting basket edits now...')
        response = GsIndexApi.edit(self.id, edit_inputs)
        report_id = response.report_id
        self.__latest_create_report = GsReportApi.get_report(response.report_id)
        report_status = self.poll_report(report_id, timeout=600, step=15)
        if report_status != ReportStatus.done:
            raise MqError(f'The basket edit report\'s status is {status}. The current rebalance request will \
                            not be submitted in the meantime.')
        _logger.info('Your basket edits have completed successfuly. Submitting rebalance request now...')
        response = GsIndexApi.rebalance(self.id, rebal_inputs)
        return response

    def __finish_populating_attributes_for_existing_basket(self):
        """ Populates all values not originally fetched during initialization due to required API calls """
        if self.__populate_api_attrs:
            position_set = GsAssetApi.get_latest_positions(self.id, PositionType.ANY)
            report = get(self, '__latest_create_report', self.__get_latest_create_report())
            self.__divisor = get(position_set, 'divisor')
            self.__initial_price = get(GsIndexApi.initial_price(self.id, dt.date.today()), 'price')
            self.__parent_basket = None if self.__clone_parent_id is None else \
                get(GsAssetApi.get_asset(self.__clone_parent_id), 'id')
            self.__position_set = PositionSet.from_target(position_set)
            self.__publish_to_bloomberg = get(report, 'parameters.publish_to_bloomberg')
            self.__publish_to_factset = get(report, 'parameters.publish_to_factset')
            self.__publish_to_reuters = get(report, 'parameters.publish_to_reuters')
            set_(self.__initial_state, 'divisor', self.__divisor)
            set_(self.__initial_state, 'initial_price', self.__initial_price)
            set_(self.__initial_state, 'position_set', self.__position_set)
            set_(self.__initial_state, 'publish_to_bloomberg', self.__publish_to_bloomberg)
            set_(self.__initial_state, 'publish_to_factset', self.__publish_to_factset)
            set_(self.__initial_state, 'publish_to_reuters', self.__publish_to_reuters)
            self.__initial_positions = set(deepcopy(self.__position_set.positions))
            self.__populate_api_attrs = False

    def __get_gs_asset(self, identifier: str) -> GsAsset:
        """ Resolves basket identifier during initialization """
        response = GsAssetApi.resolve_assets(identifier=[identifier], fields=['id'], limit=1)[identifier]
        if len(response) == 0 or get(response, '0.id') is None:
            raise MqValueError(f'Basket could not be found using identifier {identifier}')
        return GsAssetApi.get_asset(get(response, '0.id'))

    def __get_latest_create_report(self) -> Report:
        """ Used to find baskets's most recent price/publish info """
        report = GsReportApi.get_reports(limit=1, position_source_id=self.id, report_type='Basket Create',
                                         order_by='>latestExecutionTime')
        return get(report, '0')

    def __get_updates(self) -> Tuple[Optional[CustomBasketsEditInputs], Optional[CustomBasketsRebalanceInputs]]:
        """ Compares initial and current basket state to determine if updates require edit/rebalance """
        edit_inputs, rebal_inputs, pricing, publish = {}, {}, {}, {}
        update_publish_params = False

        for prop in CustomBasketsEditInputs.properties():
            if get(self.__initial_state, prop) != get(self, prop):
                set_(edit_inputs, prop, get(self, prop))
        for prop in CustomBasketsRebalanceInputs.properties():
            if prop != 'position_set' and get(self.__initial_state, prop) != get(self, prop):
                set_(rebal_inputs, prop, get(self, prop))
        for prop in CustomBasketsPricingParameters.properties():
            if get(self.__initial_state, prop) != get(self, prop):
                set_(pricing, prop, get(self, prop))
        for prop in PublishParameters.properties():
            if get(self.__initial_state, prop) != get(self, prop):
                update_publish_params = True
            set_(publish, prop, get(self, prop))

        curr_positions = set(self.position_set.positions)
        position_set_changed = False if self.__initial_positions == curr_positions else True

        # handle nested objects and make sure required/default values are input correctly
        if len(rebal_inputs) or len(pricing) or position_set_changed:
            set_(rebal_inputs, 'position_set', self.position_set.to_target(common=False))
            set_(rebal_inputs, 'pricing_parameters', CustomBasketsPricingParameters(**pricing))

        # publish params can be sent during edit or rebal, so we choose depending on current payload states
        if update_publish_params:
            publish = PublishParameters(**publish)
            set_(rebal_inputs if len(rebal_inputs) else edit_inputs, 'publish_parameters', publish)

        edit_inputs = None if not len(edit_inputs) else CustomBasketsEditInputs(**edit_inputs)
        rebal_inputs = None if not len(rebal_inputs) else CustomBasketsRebalanceInputs(**rebal_inputs)
        return edit_inputs, rebal_inputs

    def __populate_current_attributes_for_existing_basket(self, gs_asset: GsAsset):
        """ Current basket settings for existing basket """
        self.__clone_parent_id = get(gs_asset, 'parameters.cloneParentId')
        self.__default_backcast = get(gs_asset, 'parameters.defaultBackcast')
        self.__description = get(gs_asset, 'description')
        self.__flagship = get(gs_asset, 'parameters.flagship')
        self.__gs_asset_type = get(gs_asset, 'type')
        self.__hedge_id = get(gs_asset, 'parameters.hedgeId')
        self.__include_price_history = False
        self.__live_date = get(gs_asset, 'liveDate')
        self.__return_type = get(gs_asset, 'parameters.indexCalculationType')
        self.__ticker = get(gs_asset, 'xref.ticker')

        self.__initial_state = {}
        for prop in CustomBasketsEditInputs.properties().union(CustomBasketsRebalanceInputs.properties(),
                                                               CustomBasketsPricingParameters.properties(),
                                                               PublishParameters.properties()):
            set_(self.__initial_state, prop, get(self, prop))

    def __populate_default_attributes_for_new_basket(self, **kwargs):
        """ Default basket settings prior to creation """
        self.__allow_ca_restricted_assets = get(kwargs, 'allow_ca_restricted_assets')
        self.__allow_limited_access_assets = get(kwargs, 'allow_limited_access_assets')
        self.__clone_parent_id = get(kwargs, 'clone_parent_id')
        self.__currency = get(kwargs, 'currency')
        self.__default_backcast = get(kwargs, 'default_backcast', True)
        self.__description = get(kwargs, 'description')
        self.__divisor = get(kwargs, 'divisor')
        self.__hedge_id = get(kwargs, 'hedge_id')
        self.__include_price_history = get(kwargs, 'include_price_history', False)
        self.__initial_price = get(kwargs, 'initial_price', 100) if self.__divisor is None else None
        self.__name = get(kwargs, 'name')
        self.__parent_basket = get(kwargs, 'parent_basket')
        if self.__parent_basket is not None and self.__clone_parent_id is None:
            self.__clone_parent_id = get(self.__get_gs_asset(self.__parent_basket), 'id')
        self.__position_set = get(kwargs, 'position_set')
        self.__publish_to_bloomberg = get(kwargs, 'publish_to_bloomberg', True)
        self.__publish_to_factset = get(kwargs, 'publish_to_factset', False)
        self.__publish_to_reuters = get(kwargs, 'publish_to_reuters', False)
        self.__return_type = get(kwargs, 'return_type')
        self.__target_notional = get(kwargs, 'target_notional', 10000000)
        self.__ticker = get(kwargs, 'ticker')

    def __set_error_messages(self, user_is_admin: bool, user_is_internal: bool, existing_basket_initialized: bool):
        """ Errors to check for based on current user/basket state """
        errors = []
        if not user_is_admin:
            errors.append(ErrorMessage.NON_ADMIN)
        if not user_is_internal:
            errors.append(ErrorMessage.NON_INTERNAL)
        if not existing_basket_initialized:
            errors.append(ErrorMessage.UNINITIALIZED)
        else:
            errors.append(ErrorMessage.UNMODIFIABLE)
        self.__error_messages = set(errors)

    def __validate_ticker(self, ticker: str):
        """ Blocks ticker setter if entry is invalid """
        if not len(ticker) == 8:
            raise MqValueError('Invalid ticker: must be 8 characters')
        GsIndexApi.validate_ticker(ticker)
        if not ticker[:2] == 'GS':
            _logger.info('Remember to prefix your ticker with \'GS\' if you\'d like to \
                publish your basket to Bloomberg')
