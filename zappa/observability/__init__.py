"""
Zappa observability helpers.

This package bundles three small, dependency-light utilities used to make
Lambda executions and deployments easier to operate:

* :mod:`zappa.observability.tracing`     - request trace-id propagation
* :mod:`zappa.observability.structured_logging` - JSON log entries that stay
  compatible with the ``zappa tail`` parser
* :mod:`zappa.observability.metrics`     - custom CloudWatch metric reporting

The modules only depend on the Python standard library; boto3 is imported
lazily by the metrics helper so that log/tracing code keeps working in
environments where boto3 is unavailable.
"""

from .tracing import (
    TRACE_ID_ENV_VAR,
    TRACE_ID_HEADER,
    TRACE_ID_WSGI_KEY,
    TRACE_ID_WSGI_HTTP_HEADER,
    extract_trace_id,
    generate_trace_id,
)
from .structured_logging import (
    log_event,
    build_access_log,
    render_structured,
)
from .metrics import (
    DEFAULT_NAMESPACE,
    MetricReporter,
    Timer,
)

__all__ = [
    'TRACE_ID_ENV_VAR',
    'TRACE_ID_HEADER',
    'TRACE_ID_WSGI_KEY',
    'TRACE_ID_WSGI_HTTP_HEADER',
    'extract_trace_id',
    'generate_trace_id',
    'log_event',
    'build_access_log',
    'render_structured',
    'DEFAULT_NAMESPACE',
    'MetricReporter',
    'Timer',
]
