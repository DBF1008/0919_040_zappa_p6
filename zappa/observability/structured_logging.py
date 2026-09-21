"""
Structured logging helpers.

Every helper emits a single-line JSON object which is easy to ingest with
log filters/Insights while remaining fully compatible with the heuristics
that the ``zappa tail`` command uses to parse Lambda output:

* HTTP access logs keep the Apache Common Log Format line at the *front* of
  the message, so it still starts with the remote IP and is recognised by
  ``zappa tail --http``.
* Generic events never start with an IP-like token and are therefore shown
  by ``zappa tail --non-http``.
* Nothing relies on the ``START``/``REPORT``/``END RequestId`` lines that
  ``zappa tail`` discards.
"""

import json
import logging
from datetime import datetime

# ISO-8601 with milliseconds, which CloudWatch Insights can parse directly.
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'


def render_structured(fields):
    """
    Serialise a flat dict as a compact, single-line JSON string.

    Non-JSON-serialisable values (datetimes, exceptions, ...) are coerced to
    strings so logging never raises.
    """

    payload = {}
    for key, value in fields.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            value = str(value)
        payload[key] = value
    return json.dumps(payload, sort_keys=True, default=str, separators=(',', ':'))


def log_event(logger, event_name, level=logging.INFO, trace_id=None, **fields):
    """
    Emit a structured log entry.

    The entry is a JSON object with at least ``timestamp``, ``event`` and
    (when available) ``trace_id`` keys.  Extra keyword arguments are merged
    into the same object.

    :returns: the rendered log string (handy for assertions in tests).
    """

    record = {
        'timestamp': datetime.utcnow().strftime(TIMESTAMP_FORMAT),
        'event': event_name,
    }
    if trace_id is not None:
        record['trace_id'] = trace_id
    record.update(fields)

    rendered = render_structured(record)
    logger.log(level, rendered)
    return rendered


def build_access_log(apache_line, trace_id=None, response_time_ms=None,
                     status_code=None, method=None, path=None, **extra):
    """
    Build the access-log string for an HTTP request.

    ``apache_line`` is the unchanged Common Log Format line produced by
    ``requestlogger.ApacheFormatter``; it remains the first token on the line
    for ``zappa tail`` compatibility.  A compact JSON document containing the
    trace id and request metrics is appended after a separator.

    :returns: the full string that should be passed to ``logger.info``.
    """

    details = {
        'log_format': 'zappa_access_v1',
    }
    if trace_id is not None:
        details['trace_id'] = trace_id
    if response_time_ms is not None:
        details['response_time_ms'] = round(float(response_time_ms), 3)
    if status_code is not None:
        details['status_code'] = status_code
    if method is not None:
        details['method'] = method
    if path is not None:
        details['path'] = path
    details.update(extra)

    rendered = '{apache} | {json}'.format(
        apache=apache_line,
        json=render_structured(details),
    )
    # Append the trace id as a bare UUID token at the end so the simple
    # UUID colouring heuristic in `zappa tail` highlights it and so the log
    # line can be grepped by trace id without parsing JSON.
    if trace_id is not None:
        rendered = '{line} trace_id {trace_id}'.format(
            line=rendered, trace_id=trace_id)
    return rendered
