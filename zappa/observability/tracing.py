"""
Request trace-id helpers.

A single trace id is attached to every Lambda invocation and propagated to
the WSGI environ, structured log entries and asynchronous task messages so
that every CloudWatch log line emitted while servicing the same logical
request (including follow-up Lambda invocations triggered via
``zappa.asynchronous``) can be filtered together with ``zappa tail``.

Resolution order, first non-empty value wins:

1. Inbound ``X-Zappa-Trace-Id`` / ``X-Request-Id`` HTTP header, allowing
   upstream callers to continue an existing trace.
2. API Gateway ``requestContext.requestId``.
3. Lambda runtime ``context.aws_request_id`` (also exported by AWS as the
   ``AWS_REQUEST_ID``-style ``context`` object).
4. A freshly generated UUID4.
"""

import os
import uuid

TRACE_ID_ENV_VAR = 'ZAPPA_TRACE_ID'

# Canonical header name as exposed on the WSGI environ after
# ``titlecase_keys`` runs in ``zappa.wsgi`` (``HTTP_X_ZAPPA_TRACE_ID``).
TRACE_ID_HEADER = 'X-Zappa-Trace-Id'
TRACE_ID_HEADER_FALLBACK = 'X-Request-Id'

# WSGI environ key holding the trace id for user applications.
TRACE_ID_WSGI_KEY = 'zappa.trace_id'

# Also exposed as a regular (non-HTTP prefixed) WSGI key per PEP 3333.
TRACE_ID_WSGI_HTTP_HEADER = 'HTTP_X_ZAPPA_TRACE_ID'


def generate_trace_id():
    """Return a new, globally unique trace id string."""
    return str(uuid.uuid4())


def _header_value(headers, name):
    """
    Case-insensitive header lookup.

    Lambda events from API Gateway use canonical ``Title-Case`` header names
    while ALB forwards lower-case names.
    """
    if not headers:
        return None
    if name in headers:
        return headers[name]
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def extract_trace_id(event=None, context=None, headers=None):
    """
    Determine the trace id for an invocation.

    :param event: raw Lambda event dict (may be ``None`` for raw invocations).
    :param context: Lambda context object (anything exposing
        ``aws_request_id``), optional.
    :param headers: already-merged headers dict. When not given, the headers
        are pulled from the event using both the single- and multi-value
        shapes that API Gateway / ALB provide.
    :returns: a non-empty trace id string.
    """

    if headers is None and event:
        headers = dict(event.get('headers') or {})
        multi_headers = event.get('multiValueHeaders') or {}
        for key, values in multi_headers.items():
            if key not in headers and values:
                headers[key] = values[0]

    trace_id = _header_value(headers, TRACE_ID_HEADER)
    if not trace_id:
        trace_id = _header_value(headers, TRACE_ID_HEADER_FALLBACK)

    if not trace_id and event:
        request_context = event.get('requestContext') or {}
        trace_id = request_context.get('requestId')

    if not trace_id and context is not None:
        trace_id = getattr(context, 'aws_request_id', None)

    if not trace_id:
        trace_id = os.environ.get(TRACE_ID_ENV_VAR)

    if not trace_id:
        trace_id = generate_trace_id()

    return trace_id
