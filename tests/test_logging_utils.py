from __future__ import annotations

import json
import logging

from spot_vision.logging_utils import JsonFormatter


def test_json_formatter_preserves_explicit_prototype_payload():
    record = logging.LogRecord('test', logging.DEBUG, __file__, 1, 'frame %s', (4,), None)
    record.prototype = {'type': 'frame', 'sequence': 4}
    payload = json.loads(JsonFormatter().format(record))
    assert payload['message'] == 'frame 4'
    assert payload['prototype'] == {'type': 'frame', 'sequence': 4}
