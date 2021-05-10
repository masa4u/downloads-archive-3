"""
Copyright 2018 Goldman Sachs.
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

import types

import pytest

from gs_quant.timeseries import *

dummy_series = pd.Series([191.63, 184.31, 184.09, 179.67, 178.83, 176.8, 176.7, 175.92, 172.77, 168.01,
                          171.5, 169.25, 168.41, 160.05, 156.35, 162.93, 165.41, 163.03, 167.05, 172.03,
                          169.51, 175.05, 176.02, 175.37, 176.47, 176.0, 176.93, 178.72, 179.91, 197.08,
                          199.09, 202.54])

dummy_series2 = pd.Series([2790.37, 2700.06, 2695.95, 2633.08, 2637.72, 2636.78, 2651.07, 2650.54, 2599.95,
                           2545.94, 2546.16, 2506.96, 2467.42, 2416.62, 2351.1, 2467.7, 2488.83, 2485.74,
                           2506.85, 2510.03, 2447.89, 2531.94, 2549.69, 2574.41, 2584.96, 2596.64, 2596.26,
                           2582.61, 2610.3, 2616.1, 2635.96, 2670.71])


@pytest.fixture(scope='module')
def ts_map():
    return {k: v for k, v in globals().items() if isinstance(v, types.FunctionType) and
            (hasattr(v, 'plot_function') or hasattr(v, 'plot_measure') or hasattr(v, 'plot_measure_entity'))}


def test_have_docstrings(ts_map):
    for k, v in ts_map.items():
        assert v.__doc__


def test_window_to_from_dict():
    window = Window(w=1, r=2)
    window_dict = window.as_dict()

    assert window_dict['w'] == 1
    assert window_dict['r'] == 2

    window_dict = {
        'w': 1,
        'r': 2
    }

    window = Window.from_dict(window_dict)
    assert window.w == 1
    assert window.r == 2


def test_docstrings(ts_map):
    for k, v in ts_map.items():
        print('testing function', k)
        params = set()
        has_return = False
        others = 0

        lines = [x.strip() for x in v.__doc__.splitlines()]
        for line in lines:
            if not line:
                continue
            print(line)
            if line.startswith(':param'):
                params.add(re.split('[:\\s]+', line)[2])
            elif line.startswith(':return:'):
                has_return = True
            else:
                others += 1

        assert params == set(inspect.signature(v).parameters.keys()), 'all parameters documented'
        assert has_return, 'return value is documented'
        assert others >= 1, 'at least one line description'


def test_annotations(ts_map):
    for k, v in ts_map.items():
        print('testing function', k)
        annotations = v.__annotations__
        assert annotations, 'has annotations'
        assert 'return' in annotations, 'specifies return type'
        assert set(inspect.signature(v).parameters.keys()) | {'return'} == set(annotations.keys()), \
            'specifies parameter types'


def _check_measure_args(params, request_required, fn_name):
    param = params.popitem()
    name = param[1].name
    if request_required:
        assert name == 'request_id'
    if request_required or name == 'request_id':
        assert param[1].kind == inspect.Parameter.KEYWORD_ONLY
        param = params.popitem()

    assert param[1].name == 'real_time'
    assert param[1].kind == inspect.Parameter.KEYWORD_ONLY
    param = params.popitem()
    assert param[1].name == 'source'
    assert param[1].kind == inspect.Parameter.KEYWORD_ONLY

    counter = 0
    while len(params) > 0:
        param = params.popitem()
        assert param[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD, f'wrong parameter type on {fn_name}'
        if param[1].annotation == Asset:
            counter += 1

    assert counter < 2, 'no more than 1 extra asset parameter allowed'


def test_measures(ts_map):
    for k, v in ts_map.items():
        if not hasattr(v, 'plot_measure'):
            continue
        params = inspect.signature(v).parameters.copy()
        param = params.popitem(last=False)
        assert param[1].name == 'asset'
        assert param[1].annotation == Asset
        assert param[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        _check_measure_args(params, False, v.__name__)


def test_measures_on_entities(ts_map):
    for k, v in ts_map.items():
        if not hasattr(v, 'plot_measure_entity'):
            continue
        params = inspect.signature(v).parameters.copy()
        param = params.popitem(last=False)
        assert param[1].name == f'{v.entity_type.value}_id'
        assert param[1].annotation == str
        assert param[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        _check_measure_args(params, True, v.__name__)


if __name__ == '__main__':
    pytest.main(args=[__file__])
