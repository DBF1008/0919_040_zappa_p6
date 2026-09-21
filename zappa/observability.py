"""
Shared observability helpers for Zappa: structured logging, request
tracing and custom CloudWatch metrics.

The structured log lines produced here are plain ``key=value`` pairs
appended to a human readable message, so they remain fully compatible
with the parsing and colorizing logic used by the ``zappa tail``
command (see ``zappa.cli.ZappaCLI.colorize_log_entry``).
"""

import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

# Default CloudWatch namespace for Zappa custom metrics.
DEFAULT_METRIC_NAMESPACE = 'Zappa'

# WSGI environ keys which may carry an incoming trace id.
TRACE_ID_ENVIRON_KEYS = (
    'HTTP_X_TRACE_ID',
    'HTTP_X_AMZN_TRACE_ID',
    'HTTP_X_REQUEST_ID',
)

# Header names, as they appear in API Gateway/ALB events.
TRACE_ID_EVENT_HEADERS = (
    'X-Trace-Id',
    'X-Amzn-Trace-Id',
    'X-Request-Id',
    'x-trace-id',
    'x-amzn-trace-id',
    'x-request-id',
)


def generate_trace_id():
    """
    Generate a new trace id.
    """
    return str(uuid.uuid4())


def get_trace_id(event=None, context=None, environ=None):
    """
    Resolve the trace id for the current request.

    Priority: an id already attached to the WSGI environ, incoming
    trace headers, the API Gateway request id, the Lambda request id,
    and finally a freshly generated UUID.
    """
    if environ:
        existing = environ.get('zappa.trace_id')
        if existing:
            return existing
        for key in TRACE_ID_ENVIRON_KEYS:
            value = environ.get(key)
            if value:
                return value

    if event and isinstance(event, dict):
        headers = event.get('headers') or {}
        for key in TRACE_ID_EVENT_HEADERS:
            value = headers.get(key)
            if value:
                return value
        request_context = event.get('requestContext') or {}
        request_id = request_context.get('requestId')
        if request_id:
            return request_id

    aws_request_id = getattr(context, 'aws_request_id', None)
    if aws_request_id:
        return aws_request_id

    return generate_trace_id()


def format_structured(message, **fields):
    """
    Format a message with ``key=value`` pairs. Values containing
    whitespace are quoted, ``None`` values are skipped. The output is
    a single line which stays parseable by ``zappa tail``.
    """
    parts = [message]
    for key in sorted(fields.keys()):
        value = fields[key]
        if value is None:
            continue
        value = str(value)
        if any(character.isspace() for character in value):
            value = '"{}"'.format(value)
        parts.append('{}={}'.format(key, value))
    return ' '.join(parts)


def log_structured(level, message, **fields):
    """
    Emit a structured log line on the root logger.
    """
    logging.getLogger().log(level, format_structured(message, **fields))


class timer(object):
    """
    Context manager measuring wall-clock duration in milliseconds.

        with timer() as t:
            do_something()
        t.duration_ms
    """

    def __init__(self):
        self.start = None
        self.duration_ms = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *exc_info):
        self.duration_ms = (time.time() - self.start) * 1000
        return False


def metrics_disabled():
    """
    Custom metrics can be turned off with the ZAPPA_DISABLE_METRICS
    environment variable (useful for tests and local runs).
    """
    return os.environ.get('ZAPPA_DISABLE_METRICS', '').lower() in ('1', 'true', 'yes')


def put_custom_metric(cloudwatch_client, name, value, unit='Count',
                      dimensions=None, namespace=None):
    """
    Publish a single custom CloudWatch metric.

    This never raises: metric publication must not break deployments
    or request handling. Returns True if the metric was published.
    """
    if metrics_disabled():
        return False
    if cloudwatch_client is None:
        return False

    metric_datum = {
        'MetricName': name,
        'Value': value,
        'Unit': unit,
    }
    if dimensions:
        metric_datum['Dimensions'] = [
            {'Name': key, 'Value': str(val)} for key, val in dimensions.items()
        ]

    try:
        cloudwatch_client.put_metric_data(
            Namespace=namespace or DEFAULT_METRIC_NAMESPACE,
            MetricData=[metric_datum],
        )
        return True
    except Exception as e:
        logger.warning('Failed to publish CloudWatch metric %s: %s', name, e)
        return False
