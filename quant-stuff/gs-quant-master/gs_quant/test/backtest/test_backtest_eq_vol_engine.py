"""
Copyright 2018 Goldman Sachs.
Licensed under the Apache License, Version 2.0 (the 'License');
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
'AS IS' BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

from unittest import mock

import datetime as dt
from gs_quant.api.gs.backtests import GsBacktestApi
from gs_quant.backtests.strategy import Strategy
from gs_quant.backtests.triggers import PeriodicTrigger, PeriodicTriggerRequirements, DateTrigger, \
    DateTriggerRequirements, AggregateTrigger, PortfolioTrigger, PortfolioTriggerRequirements, \
    TriggerDirection
from gs_quant.backtests.actions import EnterPositionQuantityScaledAction, HedgeAction, ExitPositionAction
from gs_quant.backtests.equity_vol_engine import *
from gs_quant.common import Currency, AssetClass
from gs_quant.session import GsSession, Environment
from gs_quant.target.backtests import BacktestResult as APIBacktestResult, Backtest, OptionStyle, OptionType, \
    BacktestTradingParameters, BacktestStrategyUnderlier, BacktestStrategyUnderlierHedge, \
    VolatilityFlowBacktestParameters, BacktestTradingQuantityType, BacktestSignalSeriesItem
import pandas as pd


def set_session():
    from gs_quant.session import OAuth2Session
    OAuth2Session.init = mock.MagicMock(return_value=None)
    GsSession.use(Environment.QA, 'client_id', 'secret')


def api_mock_data() -> APIBacktestResult:
    PNL_data = [
        {'date': '2019-02-18', 'value': 0},
        {'date': '2019-02-19', 'value': -0.000000000058},
        {'date': '2019-02-20', 'value': 0.000000000262}
    ]

    risk_data = {'PNL': PNL_data}
    return APIBacktestResult('BT1', risks=risk_data)


def mock_api_response(mocker, mock_result: APIBacktestResult):
    mocker.return_value = mock_result


@mock.patch.object(GsBacktestApi, 'run_backtest')
def test_eq_vol_engine_result(mocker):
    # 1. setup strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 20)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m')
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedgetrigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='B'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedgetrigger])

    # 2. setup mock api response

    mock_api_response(mocker, api_mock_data())

    # 3. when run backtest

    set_session()
    backtest_result = EquityVolEngine.run_backtest(strategy, start_date, end_date)

    # 4. assert response

    df = pd.DataFrame(api_mock_data().risks[FlowVolBacktestMeasure.PNL.value])
    df.date = pd.to_datetime(df.date)
    expected_pnl = df.set_index('date').value

    assert expected_pnl.equals(backtest_result.get_measure_series(FlowVolBacktestMeasure.PNL))


@mock.patch.object(GsBacktestApi, 'run_backtest')
def test_engine_mapping_basic(mocker):
    # 1. setup strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 20)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m')
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedgetrigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='B'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedgetrigger])

    # 2. setup mock api response

    mock_api_response(mocker, api_mock_data())

    # 3. when run backtest

    set_session()
    EquityVolEngine.run_backtest(strategy, start_date, end_date)

    # 4. assert API call

    backtest_parameter_args = {
        'trading_parameters': BacktestTradingParameters(
            quantity=1,
            quantity_type=BacktestTradingQuantityType.quantity.value,
            trade_in_method=TradeInMethod.FixedRoll.value,
            roll_frequency='1m'),
        'underliers': [BacktestStrategyUnderlier(
            instrument=option,
            notional_percentage=100,
            hedge=BacktestStrategyUnderlierHedge(risk_details=DeltaHedgeParameters(frequency='Daily')),
            market_model='SFK')
        ],
        'index_initial_value': 0.0,
        "measures": [FlowVolBacktestMeasure.ALL_MEASURES]
    }
    backtest_parameters = VolatilityFlowBacktestParameters.from_dict(backtest_parameter_args)

    backtest = Backtest(name="Flow Vol Backtest",
                        mq_symbol="Flow Vol Backtest",
                        parameters=backtest_parameters,
                        start_date=start_date,
                        end_date=end_date,
                        type='Volatility Flow',
                        asset_class=AssetClass.Equity,
                        currency=Currency.USD,
                        cost_netting=False)

    mocker.assert_called_with(backtest, None)


@mock.patch.object(GsBacktestApi, 'run_backtest')
def test_engine_mapping_trade_quantity(mocker):
    # 1. setup strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 20)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity=12345,
                                               trade_quantity_type=BacktestTradingQuantityType.notional)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedgetrigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='B'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedgetrigger])

    # 2. setup mock api response

    mock_api_response(mocker, api_mock_data())

    # 3. when run backtest

    set_session()
    EquityVolEngine.run_backtest(strategy, start_date, end_date)

    # 4. assert API call

    backtest_parameter_args = {
        'trading_parameters': BacktestTradingParameters(
            quantity=12345,
            quantity_type=BacktestTradingQuantityType.notional.value,
            trade_in_method=TradeInMethod.FixedRoll.value,
            roll_frequency='1m'),
        'underliers': [BacktestStrategyUnderlier(
            instrument=option,
            notional_percentage=100,
            hedge=BacktestStrategyUnderlierHedge(risk_details=DeltaHedgeParameters(frequency='Daily')),
            market_model='SFK')
        ],
        'index_initial_value': 0.0,
        "measures": [FlowVolBacktestMeasure.ALL_MEASURES]
    }
    backtest_parameters = VolatilityFlowBacktestParameters.from_dict(backtest_parameter_args)

    backtest = Backtest(name="Flow Vol Backtest",
                        mq_symbol="Flow Vol Backtest",
                        parameters=backtest_parameters,
                        start_date=start_date,
                        end_date=end_date,
                        type='Volatility Flow',
                        asset_class=AssetClass.Equity,
                        currency=Currency.USD,
                        cost_netting=False)

    mocker.assert_called_with(backtest, None)


@mock.patch.object(GsBacktestApi, 'run_backtest')
def test_engine_mapping_with_signals(mocker):
    # 1. setup strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 27)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    entry_action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity=12345,
                                                     trade_quantity_type=BacktestTradingQuantityType.notional)

    entry_signal_series = pd.Series(data={dt.date(2019, 2, 19): 1})
    entry_dates = entry_signal_series[entry_signal_series > 0].keys()

    entry_trigger = AggregateTrigger(triggers=[
        DateTrigger(trigger_requirements=DateTriggerRequirements(dates=entry_dates), actions=entry_action),
        PortfolioTrigger(trigger_requirements=PortfolioTriggerRequirements('len', 0, TriggerDirection.EQUAL))
    ])

    exit_signal_series = pd.Series(data={dt.date(2019, 2, 20): 1})
    exit_dates = exit_signal_series[exit_signal_series > 0].keys()

    exit_trigger = AggregateTrigger(triggers=[
        DateTrigger(trigger_requirements=DateTriggerRequirements(dates=exit_dates), actions=ExitPositionAction()),
        PortfolioTrigger(trigger_requirements=PortfolioTriggerRequirements('len', 0, TriggerDirection.ABOVE))
    ])

    strategy = Strategy(initial_portfolio=None, triggers=[entry_trigger, exit_trigger])

    # 2. setup mock api response

    mock_api_response(mocker, api_mock_data())

    # 3. when run backtest

    set_session()
    EquityVolEngine.run_backtest(strategy, start_date, end_date)

    # 4. assert API call

    backtest_parameter_args = {
        'trading_parameters': BacktestTradingParameters(
            quantity=12345,
            quantity_type=BacktestTradingQuantityType.notional.value,
            trade_in_method=TradeInMethod.FixedRoll.value,
            roll_frequency='1m',
            trade_in_signals=list(map(lambda x: BacktestSignalSeriesItem(x[0], int(x[1])),
                                      zip(entry_signal_series.index, entry_signal_series.values))),
            trade_out_signals=list(map(lambda x: BacktestSignalSeriesItem(x[0], int(x[1])),
                                       zip(exit_signal_series.index, exit_signal_series.values)))
        ),
        'underliers': [
            BacktestStrategyUnderlier(
                instrument=option,
                notional_percentage=100,
                hedge=BacktestStrategyUnderlierHedge(),
                market_model='SFK',
            )
        ],
        'index_initial_value': 0.0,
        "measures": [FlowVolBacktestMeasure.ALL_MEASURES]
    }
    backtest_parameters = VolatilityFlowBacktestParameters.from_dict(backtest_parameter_args)

    backtest = Backtest(name="Flow Vol Backtest",
                        mq_symbol="Flow Vol Backtest",
                        parameters=backtest_parameters,
                        start_date=start_date,
                        end_date=end_date,
                        type='Volatility Flow',
                        asset_class=AssetClass.Equity,
                        currency=Currency.USD,
                        cost_netting=False)

    mocker.assert_called_with(backtest, None)


@mock.patch.object(GsBacktestApi, 'run_backtest')
def test_engine_mapping_trade_quantity_nav(mocker):
    # 1. setup strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 20)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity=12345,
                                               trade_quantity_type=BacktestTradingQuantityType.NAV)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedgetrigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='B'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedgetrigger])

    # 2. setup mock api response

    mock_api_response(mocker, api_mock_data())

    # 3. when run backtest

    set_session()
    EquityVolEngine.run_backtest(strategy, start_date, end_date)

    # 4. assert API call

    backtest_parameter_args = {
        'trading_parameters': BacktestTradingParameters(
            quantity=12345,
            quantity_type=BacktestTradingQuantityType.NAV.value,
            trade_in_method=TradeInMethod.FixedRoll.value,
            roll_frequency='1m'),
        'underliers': [BacktestStrategyUnderlier(
            instrument=option,
            notional_percentage=100,
            hedge=BacktestStrategyUnderlierHedge(risk_details=DeltaHedgeParameters(frequency='Daily')),
            market_model='SFK')
        ],
        'index_initial_value': 12345,
        "measures": [FlowVolBacktestMeasure.ALL_MEASURES]
    }
    backtest_parameters = VolatilityFlowBacktestParameters.from_dict(backtest_parameter_args)

    backtest = Backtest(name="Flow Vol Backtest",
                        mq_symbol="Flow Vol Backtest",
                        parameters=backtest_parameters,
                        start_date=start_date,
                        end_date=end_date,
                        type='Volatility Flow',
                        asset_class=AssetClass.Equity,
                        currency=Currency.USD,
                        cost_netting=False)

    mocker.assert_called_with(backtest, None)


def test_supports_strategy():
    # 1. Valid strategy

    start_date = dt.date(2019, 2, 18)
    end_date = dt.date(2019, 2, 20)

    option = EqOption('.STOXX50E', expirationDate='3m', strikePrice='ATM', optionType=OptionType.Call,
                      optionStyle=OptionStyle.European)

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m')
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedge_trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='B'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedge_trigger])

    assert EquityVolEngine.supports_strategy(strategy)

    # 2. Invalid - no trade action

    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=None
    )
    strategy = Strategy(initial_portfolio=None, triggers=[trigger])
    assert not EquityVolEngine.supports_strategy(strategy)

    # 3. Invalid - no trade quantity

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity=None)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    strategy = Strategy(initial_portfolio=None, triggers=[trigger])
    assert not EquityVolEngine.supports_strategy(strategy)

    # 4. Invalid - no trade quantity type

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity_type=None)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    strategy = Strategy(initial_portfolio=None, triggers=[trigger])
    assert not EquityVolEngine.supports_strategy(strategy)

    # 5. Invalid - mismatch trade duration and trigger period

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='2m', trade_quantity_type=None)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    strategy = Strategy(initial_portfolio=None, triggers=[trigger])
    assert not EquityVolEngine.supports_strategy(strategy)

    # 6. Invalid - mismatch hedge trade duration and trigger period

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity_type=None)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedge_trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='B'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='M'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedge_trigger])
    assert not EquityVolEngine.supports_strategy(strategy)

    # 6. Invalid - non-daily hedge trade

    action = EnterPositionQuantityScaledAction(priceables=option, trade_duration='1m', trade_quantity_type=None)
    trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='1m'),
        actions=action)
    hedge_trigger = PeriodicTrigger(
        trigger_requirements=PeriodicTriggerRequirements(start_date=start_date, end_date=end_date, frequency='M'),
        actions=HedgeAction(EqDelta, priceables=option, trade_duration='M'))
    strategy = Strategy(initial_portfolio=None, triggers=[trigger, hedge_trigger])
    assert not EquityVolEngine.supports_strategy(strategy)
