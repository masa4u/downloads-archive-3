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

import logging
from collections import OrderedDict
from enum import Enum
from typing import Optional, Union, Dict

import pandas as pd
from pandas import Series

from gs_quant.api.gs.assets import GsAssetApi
from gs_quant.api.gs.data import QueryType, GsDataApi
from gs_quant.errors import MqValueError
from gs_quant.markets.securities import AssetIdentifier, Asset, SecurityMaster
from gs_quant.target.common import Currency as CurrencyEnum, AssetClass, AssetType, PricingLocation
from gs_quant.timeseries import ASSET_SPEC, plot_measure, MeasureDependency, GENERIC_DATE
from gs_quant.timeseries.measures import _asset_from_spec, _market_data_timed, ExtendedSeries
from gs_quant.timeseries import measures_rates as tm_rates

_logger = logging.getLogger(__name__)


class CrossCurrencyRateOptionType(Enum):
    LIBOR = 'LIBOR'
    OIS = 'OIS'
    EUROSTR = 'EUROSTR'
    SOFR = 'SOFR'
    TestRateOption = 'TestRateOption'


class TdapiCrossCurrencyRatesDefaultsProvider:
    # flag to indicate that a given property should not  be included in asset query
    EMPTY_PROPERTY = "null"

    def __init__(self, defaults: dict):
        self.defaults = defaults
        benchmark_mappings = {}
        maturity_mappings = {}
        for k, v in defaults.get("CURRENCIES").items():
            benchmark_mappings[k] = {}
            maturity_mappings[k] = {}
            for e in v:
                benchmark_mappings[k][e.get("BenchmarkType")] = e.get('rateOption')
                maturity_mappings[k][e.get("BenchmarkType")] = e.get('designatedMaturity')
        self.defaults['MAPPING'] = benchmark_mappings
        self.defaults['MATURITIES'] = maturity_mappings

    def get_rateoption_for_benchmark(self, currency: CurrencyEnum, benchmark: str):
        return self.defaults.get("MAPPING").get(currency.value).get(benchmark)

    def get_maturity_for_benchmark(self, currency: CurrencyEnum, benchmark: str):
        return self.defaults.get("MATURITIES").get(currency.value).get(benchmark)


CROSSCURRENCY_RATES_DEFAULTS = {
    "CURRENCIES": {
        "EUR": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "EUR-EURIBOR-TELERATE",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
            {"BenchmarkType": "OIS",
             "rateOption": "EUR-EONIA-OIS-COMPOUND",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]}
        ],
        "USD": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "USD-LIBOR-BBA",
             "designatedMaturity": "3m",
             "pricingLocation": ["NYC"]},
            {"BenchmarkType": "OIS",
             "rateOption": "USD-Federal Funds-H.15-OIS-COMP",
             "designatedMaturity": "3m",
             "pricingLocation": ["NYC"]}
        ],
        "GBP": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "GBP-LIBOR-BBA",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
            {"BenchmarkType": "OIS",
             "rateOption": "GBP-SONIA-COMPOUND",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]}
        ],
        "JPY": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "JPY-LIBOR-BBA",
             "designatedMaturity": "3m",
             "pricingLocation": ["TKO"]},
            {"BenchmarkType": "OIS",
             "rateOption": "JPY-TONA-OIS-COMPOUND",
             "designatedMaturity": "3m",
             "pricingLocation": ["TKO"]},
        ],
        "CHF": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "CHF-LIBOR-BBA",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
        ],
        "DKK": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "DKK-CIBOR2-DKNA13",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
        ],
        "SEK": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "SEK-STIBOR-SIDE",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
        ],
        "NOK": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "NOK-NIBOR-BBA",
             "designatedMaturity": "3m",
             "pricingLocation": ["LDN"]},
        ],
        "AUD": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "AUD-BBR-BBSW",
             "designatedMaturity": "3m",
             "pricingLocation": ["TKO"]},
        ],
        "NZD": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "NZD-BBR-FRA",
             "designatedMaturity": "3m",
             "pricingLocation": ["TKO"]},
        ],
        "CAD": [
            {"BenchmarkType": "LIBOR",
             "rateOption": "CAD-BA-CDOR",
             "designatedMaturity": "3m",
             "pricingLocation": ["NYC"]},
        ],
    },
    "COMMON": {
        "payerSpread": "ATM",
        "clearingHouse": "NONE",
        "terminationTenor": "5y",
        "effectiveDate": "0b"
    }
}
crossCurrencyRates_defaults_provider = TdapiCrossCurrencyRatesDefaultsProvider(CROSSCURRENCY_RATES_DEFAULTS)

CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK = {
    'CHF': OrderedDict([('LIBOR', 'CHF-LIBOR-BBA'), ('OIS', 'CHF-SARON-OIS-COMPOUND')]),
    'EUR': OrderedDict([('LIBOR', 'EUR-EURIBOR-TELERATE'), ('OIS', 'EUR-EONIA-OIS-COMPOUND'),
                        ('EUROSTR', 'EUR-EUROSTR-COMPOUND')]),
    'GBP': OrderedDict([('LIBOR', 'GBP-LIBOR-BBA'), ('OIS', 'GBP-SONIA-COMPOUND')]),
    'JPY': OrderedDict([('LIBOR', 'JPY-LIBOR-BBA'), ('OIS', 'JPY-TONA-OIS-COMPOUND')]),
    'USD': OrderedDict(
        [('LIBOR', 'USD-LIBOR-BBA'), ('OIS', 'USD-Federal Funds-H.15-OIS-COMP'), ('SOFR', 'USD-SOFR-COMPOUND')]),
    'SEK': {'LIBOR': 'SEK-STIBOR-SIDE'},
    'NOK': {'LIBOR': 'NOK-NIBOR-BBA'},
    'DKK': {'LIBOR': 'DKK-CIBOR2-DKNA13'},
    'AUD': {'LIBOR': 'AUD-BBR-BBSW'},
    'CAD': {'LIBOR': 'CAD-BA-CDOR'},
    'NZD': {'LIBOR': 'NZD-BBR-FRA'},
}

CURRENCY_TO_DUMMY_CROSSCURRENCY_SWAP_BBID = {
    'EUR': 'MAW8SAXPSKYA94E2',
    'GBP': 'MATDD783JM1C2GGD',
    'JPY': 'MAFMW4HJC5TDE51H',
}


def _currency_to_tdapi_crosscurrency_swap_rate_asset(asset_spec: ASSET_SPEC) -> str:
    asset = _asset_from_spec(asset_spec)
    bbid = asset.get_identifier(AssetIdentifier.BLOOMBERG_ID)
    # for each currency, get a dummy asset for checking availability
    result = CURRENCY_TO_DUMMY_CROSSCURRENCY_SWAP_BBID.get(bbid, asset.get_marquee_id())
    return result


def _get_tdapi_crosscurrency_rates_assets(allow_many=False, **kwargs) -> Union[str, list]:
    # sanitize input for asset query.
    if "pricing_location" in kwargs:
        del kwargs["pricing_location"]
    assets = GsAssetApi.get_many_assets(**kwargs)

    # change order of basis swap legs and check if swap in dataset
    if len(assets) == 0 and ('asset_parameters_payer_rate_option' in kwargs):  # flip legs
        kwargs['asset_parameters_payer_rate_option'], kwargs['asset_parameters_receiver_rate_option'] = \
            kwargs['asset_parameters_receiver_rate_option'], kwargs['asset_parameters_payer_rate_option']
        if 'asset_parameters_payer_designated_maturity' in kwargs:
            kwargs['asset_parameters_payer_designated_maturity'], kwargs[
                'asset_parameters_receiver_designated_maturity'] = \
                kwargs['asset_parameters_receiver_designated_maturity'], kwargs[
                    'asset_parameters_payer_designated_maturity']
        if 'asset_parameters_payer_currency' in kwargs:
            kwargs['asset_parameters_payer_currency'], kwargs['asset_parameters_receiver_currency'] = \
                kwargs['asset_parameters_receiver_currency'], kwargs['asset_parameters_payer_currency']
        assets = GsAssetApi.get_many_assets(**kwargs)

    if len(assets) == 0 and ('asset_parameters_clearing_house' in kwargs):  # test without the clearing house
        if kwargs['asset_parameters_clearing_house'] == tm_rates._ClearingHouse.NONE.value:
            del kwargs['asset_parameters_clearing_house']
            assets = GsAssetApi.get_many_assets(**kwargs)

    # change order of basis swap legs and check if swap in dataset
    if len(assets) == 0 and ('asset_parameters_payer_rate_option' in kwargs):  # flip legs
        kwargs['asset_parameters_payer_rate_option'], kwargs['asset_parameters_receiver_rate_option'] = \
            kwargs['asset_parameters_receiver_rate_option'], kwargs['asset_parameters_payer_rate_option']
        if 'asset_parameters_payer_designated_maturity' in kwargs:
            kwargs['asset_parameters_payer_designated_maturity'], kwargs[
                'asset_parameters_receiver_designated_maturity'] = \
                kwargs['asset_parameters_receiver_designated_maturity'], kwargs[
                    'asset_parameters_payer_designated_maturity']
        if 'asset_parameters_payer_currency' in kwargs:
            kwargs['asset_parameters_payer_currency'], kwargs['asset_parameters_receiver_currency'] = \
                kwargs['asset_parameters_receiver_currency'], kwargs['asset_parameters_payer_currency']
        assets = GsAssetApi.get_many_assets(**kwargs)

    if len(assets) > 1:
        # term structure measures need multiple assets
        if ('asset_parameters_termination_date' not in kwargs) or (
                'asset_parameters_effective_date' not in kwargs) or allow_many:
            return [asset.id for asset in assets]
        else:
            raise MqValueError('Specified arguments match multiple assets')
    elif len(assets) == 0:
        raise MqValueError('Specified arguments did not match any asset in the dataset' + str(kwargs))
    else:
        return assets[0].id


def _check_crosscurrency_rateoption_type(currency, benchmark_type: Union[CrossCurrencyRateOptionType, str]) \
        -> CrossCurrencyRateOptionType:
    if isinstance(benchmark_type, str):
        if benchmark_type.upper() in CrossCurrencyRateOptionType.__members__:
            benchmark_type = CrossCurrencyRateOptionType[benchmark_type.upper()]
        else:
            raise MqValueError(
                benchmark_type.upper() + ' is not valid, pick one among ' +
                ', '.join([x.value for x in CrossCurrencyRateOptionType]))

    if isinstance(benchmark_type, CrossCurrencyRateOptionType) and \
            benchmark_type.value not in CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK[currency.value].keys():
        raise MqValueError('%s is not supported for %s', benchmark_type.value, currency.value)
    else:
        return benchmark_type


def _get_crosscurrency_swap_leg_defaults(currency: CurrencyEnum,
                                         benchmark_type: CrossCurrencyRateOptionType = None) -> Dict:
    pricing_location = tm_rates.CURRENCY_TO_PRICING_LOCATION.get(currency, PricingLocation.LDN)
    # default benchmark types
    if benchmark_type is None:
        benchmark_type = CrossCurrencyRateOptionType(
            str(list(CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK[currency.value].keys())[0]))
    benchmark_type_input = CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK[currency.value].get(benchmark_type.value, "")
    designated_maturity = crossCurrencyRates_defaults_provider.get_maturity_for_benchmark(currency,
                                                                                          benchmark_type.value)
    return dict(currency=currency, rateOption=benchmark_type_input, designatedMaturity=designated_maturity,
                pricing_location=pricing_location)


def _get_crosscurrency_swap_csa_terms(curr: str, crosscurrencyindextype: str) -> dict:
    return dict(csaTerms=curr + '-1')


def _get_crosscurrency_swap_data(asset1: Asset, asset2: Asset, swap_tenor: str, rateoption_type: str = None,
                                 forward_tenor: Optional[GENERIC_DATE] = None,
                                 clearing_house: tm_rates._ClearingHouse = None,
                                 source: str = None, real_time: bool = False,
                                 query_type: QueryType = QueryType.SWAP_RATE) -> pd.DataFrame:
    if real_time:
        raise NotImplementedError('realtime swap_rate not implemented for anything but rates')

    currency1 = CurrencyEnum(asset1.get_identifier(AssetIdentifier.BLOOMBERG_ID))
    currency2 = CurrencyEnum(asset2.get_identifier(AssetIdentifier.BLOOMBERG_ID))

    if currency1.value not in CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK.keys():
        raise NotImplementedError('Data not available for {} crosscurrency swap rates'.format(currency1.value))
    if currency2.value not in CURRENCY_TO_XCCY_SWAP_RATE_BENCHMARK.keys():
        raise NotImplementedError('Data not available for {} crosscurrency swap rates'.format(currency2.value))

    rateoption_type1 = _check_crosscurrency_rateoption_type(currency1, rateoption_type)
    rateoption_type2 = _check_crosscurrency_rateoption_type(currency2, rateoption_type)

    if rateoption_type1 != rateoption_type2:
        raise MqValueError('The two currencies do not both support the rate Option type ' + rateoption_type)
    rateoption_type = rateoption_type1

    clearing_house = tm_rates._check_clearing_house(clearing_house)

    defaults1 = _get_crosscurrency_swap_leg_defaults(currency1, rateoption_type)
    defaults2 = _get_crosscurrency_swap_leg_defaults(currency2, rateoption_type)

    if not (tm_rates._is_valid_relative_date_tenor(swap_tenor)):
        raise MqValueError('invalid swap tenor ' + swap_tenor)

    if defaults1["pricing_location"] == PricingLocation.NYC:
        location = defaults2["pricing_location"]
    else:
        location = defaults1["pricing_location"]

    forward_tenor = tm_rates._check_forward_tenor(forward_tenor)
    fixed_rate = 'ATM'
    kwargs = dict(type='XccySwapMTM',
                  asset_parameters_termination_date=swap_tenor,
                  asset_parameters_effective_date=forward_tenor,
                  asset_parameters_payer_spread=fixed_rate,
                  # asset_parameters_payer_currency=defaults1['currency'].value,
                  asset_parameters_payer_rate_option=defaults1['rateOption'],
                  # asset_parameters_payer_designated_maturity=defaults1['designatedMaturity'],
                  # asset_parameters_receiver_currency=defaults2['currency'].value,
                  asset_parameters_receiver_rate_option=defaults2['rateOption'],
                  # asset_parameters_receiver_designated_maturity=defaults2['designatedMaturity'],
                  asset_parameters_clearing_house=clearing_house.value,
                  pricing_location=location
                  )

    rate_mqid = _get_tdapi_crosscurrency_rates_assets(**kwargs)

    _logger.debug(f'where asset= {rate_mqid}, swap_tenor={swap_tenor}, forward_tenor={forward_tenor}, '
                  f'payer_currency={defaults1["currency"].value}, payer_rate_option={defaults1["rateOption"]}, '
                  f'payer_designated_maturity={defaults1["designatedMaturity"]}, '
                  f'receiver_currency={defaults2["currency"].value}, receiver_rate_option={defaults2["rateOption"]}, '
                  f'receiver_designated_maturity={defaults2["designatedMaturity"]}, '
                  f'clearing_house={clearing_house.value}, pricing_location={location.value}')
    q = GsDataApi.build_market_data_query([rate_mqid], query_type, source=source,
                                          real_time=real_time)
    _logger.debug('q %s', q)
    df = _market_data_timed(q)
    return df


@plot_measure((AssetClass.Cash, AssetClass.FX,), (AssetType.Currency, AssetType.Cross,),
              [MeasureDependency(id_provider=_currency_to_tdapi_crosscurrency_swap_rate_asset,
                                 query_type=QueryType.SWAP_RATE)])
def crosscurrency_swap_rate(asset: Asset, swap_tenor: str, rateoption_type: str = None,
                            forward_tenor: Optional[GENERIC_DATE] = None,
                            clearing_house: tm_rates._ClearingHouse = None,
                            source: str = None, real_time: bool = False) -> Series:
    """
    GS end-of-day Zero Coupon CrossCurrency Swap curves across major currencies.

    :param asset: asset object loaded from security master
    :param swap_tenor: relative date representation of expiration date e.g. 1m
    :param rateoption_type: benchmark type e.g. LIBOR
    :param forward_tenor: absolute / relative date representation of forward starting point eg: '1y' or 'Spot' for
            spot starting swaps, 'imm1' or 'frb1'
    :param clearing_house: Example - "LCH", "EUREX", "JSCC", "CME"
    :param source: name of function caller
    :param real_time: whether to retrieve intraday data instead of EOD
    :return: swap rate curve
    """

    if asset.get_type().value == AssetType.Cross.value:
        pair = asset.name
        [under, over] = [pair[i:i + 3] for i in range(0, 6, 3)]
        asset1 = SecurityMaster.get_asset(under, AssetIdentifier.BLOOMBERG_ID)
        asset2 = SecurityMaster.get_asset(over, AssetIdentifier.BLOOMBERG_ID)
    elif asset.get_type().value == AssetType.Currency.value:
        asset1 = asset
        asset2 = SecurityMaster.get_asset("USD", AssetIdentifier.BLOOMBERG_ID)
    else:
        raise MqValueError('Asset type not supported ' + asset.get_type().value)

    df = _get_crosscurrency_swap_data(asset1=asset1, asset2=asset2, swap_tenor=swap_tenor,
                                      rateoption_type=rateoption_type,
                                      forward_tenor=forward_tenor,
                                      clearing_house=clearing_house, source=source,
                                      real_time=real_time, query_type=QueryType.XCCY_SWAP_SPREAD)

    series = ExtendedSeries() if df.empty else ExtendedSeries(df['xccySwapSpread'])
    series.dataset_ids = getattr(df, 'dataset_ids', ())
    return series
