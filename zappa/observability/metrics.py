"""
Custom CloudWatch metrics.

``MetricReporter`` buffers ``put_metric_data`` compatible metric dicts and
flushes them in a single, best-effort API call.  Reporting is wrapped in a
broad ``try/except`` so that a metrics misconfiguration (missing IAM
permission, regional outage, ...) can never break a request or a deployment.

A small ``Timer`` context manager records elapsed milliseconds and, when an
exception escapes, emits a failure count instead of a success count.
"""

import logging
import time
from contextlib import ContextDecorator

logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = 'Zappa/Observability'

# CloudWatch rejects batches larger than 20 (and metric values must be finite
# numbers), flush defensively once we reach the documented limit.
_MAX_BATCH_SIZE = 20


class MetricReporter(object):
    """
    Accumulate custom CloudWatch metric datums and flush them on demand.

    :param cloudwatch_client: a boto3 ``cloudwatch`` client.  May be ``None``
        (e.g. unit tests); in that case datums are still buffered and flushed
        to the debug log instead of calling AWS.
    :param namespace: CloudWatch metric namespace.
    :param enabled: when ``False`` every public call becomes a no-op.  This is
        the switch used to keep the default behaviour of Zappa unchanged.
    """

    def __init__(self, cloudwatch_client=None, namespace=DEFAULT_NAMESPACE,
                 enabled=True, default_dimensions=None):
        self.cloudwatch_client = cloudwatch_client
        self.namespace = namespace
        self.enabled = enabled
        self.default_dimensions = default_dimensions or {}
        self._datums = []

    def _build_dimensions(self, dimensions=None):
        merged = {key: value
                  for key, value in self.default_dimensions.items()
                  if value is not None}
        if dimensions:
            for key, value in dimensions.items():
                if value is None:
                    continue
                merged[key] = str(value)
        if not merged:
            return None
        return [{'Name': key, 'Value': value}
                for key, value in sorted(merged.items())]

    def add_metric(self, name, value, unit='None', dimensions=None):
        """Buffer a single scalar metric datum."""
        if not self.enabled or value is None:
            return
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            logger.debug('Ignoring non-numeric metric %s=%r', name, value)
            return

        datum = {
            'MetricName': name,
            'Value': numeric_value,
            'Unit': unit,
        }
        dims = self._build_dimensions(dimensions)
        if dims:
            datum['Dimensions'] = dims

        self._datums.append(datum)

        if len(self._datums) >= _MAX_BATCH_SIZE:
            self.flush()

    def record_latency(self, name, milliseconds, dimensions=None):
        """Convenience wrapper for a millisecond duration metric."""
        self.add_metric(name, milliseconds, unit='Milliseconds',
                        dimensions=dimensions)

    def record_count(self, name, count=1, dimensions=None):
        """Convenience wrapper for a count metric."""
        self.add_metric(name, count, unit='Count', dimensions=dimensions)

    @property
    def datums(self):
        """Copied view of the buffered datums (mainly useful in tests)."""
        return list(self._datums)

    def flush(self):
        """
        Send all buffered datums to CloudWatch.

        Returns the number of datums that were buffered when flush was called
        (0 when disabled or empty).  Never raises.
        """
        if not self.enabled or not self._datums:
            return 0

        pending = self._datums
        self._datums = []

        if self.cloudwatch_client is None:
            logger.debug('CloudWatch client unavailable, dropping %d metric(s): %s',
                         len(pending), pending)
            return len(pending)

        try:
            # put_metric_data accepts at most 20 datums per call.
            for offset in range(0, len(pending), _MAX_BATCH_SIZE):
                batch = pending[offset:offset + _MAX_BATCH_SIZE]
                self.cloudwatch_client.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch,
                )
        except Exception as e:  # pragma: no cover - network/permission errors
            logger.warning('Failed to publish %d CloudWatch metric(s): %s',
                           len(pending), e)
            return 0
        return len(pending)


class Timer(ContextDecorator):
    """
    Context manager / decorator that measures wall-clock latency.

    On clean exit it records ``<name>`` in milliseconds and a
    ``<name>.Success`` count.  If an exception escapes, it records a
    ``<name>.Failure`` count and stores the elapsed time on the exception
    path before re-raising.

    ``structured_logging.log_event`` is called at the same time so slow
    requests are visible in CloudWatch Logs even without opening the metrics
    console.
    """

    def __init__(self, name, reporter=None, dimensions=None,
                 trace_id=None, logger=None, emit_log=True, extra=None):
        self.name = name
        self.reporter = reporter
        self.dimensions = dimensions
        self.trace_id = trace_id
        self.logger = logger
        self.emit_log = emit_log
        self.extra = extra or {}
        self.elapsed_ms = None
        self.succeeded = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed_ms = (time.time() - self._start) * 1000.0
        self.succeeded = exc_type is None

        if self.reporter is not None:
            self.reporter.record_latency(self.name, self.elapsed_ms,
                                         dimensions=self.dimensions)
            outcome = 'Success' if self.succeeded else 'Failure'
            self.reporter.record_count(
                '{name}.{outcome}'.format(name=self.name, outcome=outcome),
                dimensions=self.dimensions,
            )

        if self.emit_log:
            # Imported lazily to avoid an import cycle at package load time.
            from .structured_logging import log_event
            event_logger = self.logger or logging.getLogger()
            fields = dict(self.extra)
            fields['duration_ms'] = round(self.elapsed_ms, 3)
            fields['outcome'] = 'success' if self.succeeded else 'failure'
            if exc is not None:
                fields['error'] = '{module}.{type}: {message}'.format(
                    module=exc.__class__.__module__,
                    type=exc.__class__.__name__,
                    message=exc,
                )
            log_event(event_logger,
                      'timing.' + self.name,
                      level=logging.ERROR if exc is not None else logging.INFO,
                      trace_id=self.trace_id,
                      **fields)

        # Never swallow the exception.
        return False
