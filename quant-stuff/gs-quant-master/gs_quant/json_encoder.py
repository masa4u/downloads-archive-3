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
from enum import Enum
import json
import pandas as pd

from gs_quant.base import Base


def default(o):
    if isinstance(o, datetime.datetime):
        return o.strftime('%Y-%m-%dT%H:%M:%S.') + '{:06d}'.format(o.microsecond)[:-3] + 'Z'
    if isinstance(o, datetime.date):
        return o.isoformat()
    elif isinstance(o, Enum):
        return o.value
    elif isinstance(o, pd.DataFrame):
        return o.to_json()
    elif isinstance(o, Base):
        return o.to_json()


class JSONEncoder(json.JSONEncoder):

    def default(self, o):
        ret = default(o)
        return super().default(o) if ret is None else ret
