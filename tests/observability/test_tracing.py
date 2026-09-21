import os
import unittest

from zappa.observability import (
    TRACE_ID_ENV_VAR,
    TRACE_ID_WSGI_KEY,
    extract_trace_id,
    generate_trace_id,
)
from zappa.observability.tracing import TRACE_ID_HEADER


class FakeLambdaContext(object):
    def __init__(self, request_id):
        self.aws_request_id = request_id


class TraceIdTests(unittest.TestCase):

    def test_generate_trace_id_is_unique_uuid4(self):
        first = generate_trace_id()
        second = generate_trace_id()
        self.assertNotEqual(first, second)
        # UUID4 with dashes -> 5 groups, matching zappa tail UUID colouring.
        self.assertEqual(first.count('-'), 4)

    def test_trace_header_wins(self):
        event = {
            'headers': {'X-Zappa-Trace-Id': 'trace-from-caller'},
            'requestContext': {'requestId': 'gw-request-id'},
        }
        self.assertEqual(extract_trace_id(event=event), 'trace-from-caller')

    def test_trace_header_is_case_insensitive_for_alb(self):
        event = {
            'headers': {'x-zappa-trace-id': 'alb-trace'},
            'requestContext': {'requestId': 'gw-request-id'},
        }
        self.assertEqual(extract_trace_id(event=event), 'alb-trace')

    def test_x_request_id_header_fallback(self):
        event = {
            'headers': {'X-Request-Id': 'req-42'},
            'requestContext': {},
        }
        self.assertEqual(extract_trace_id(event=event), 'req-42')

    def test_multi_value_header_supported(self):
        event = {
            'headers': {},
            'multiValueHeaders': {'X-Zappa-Trace-Id': ['multi-trace']},
            'requestContext': {},
        }
        self.assertEqual(extract_trace_id(event=event), 'multi-trace')

    def test_api_gateway_request_id_fallback(self):
        event = {
            'headers': {},
            'requestContext': {'requestId': 'gw-request-id'},
        }
        self.assertEqual(extract_trace_id(event=event), 'gw-request-id')

    def test_lambda_context_request_id_fallback(self):
        event = {'headers': {}, 'requestContext': {}}
        context = FakeLambdaContext('aws-request-1')
        self.assertEqual(extract_trace_id(event=event, context=context),
                         'aws-request-1')

    def test_generated_when_nothing_available(self):
        trace_id = extract_trace_id(event={'headers': {},
                                           'requestContext': {}})
        self.assertEqual(trace_id.count('-'), 4)

    def test_empty_event_and_context_generate_id(self):
        trace_id = extract_trace_id()
        self.assertTrue(trace_id)

    def test_environment_variable_fallback(self):
        event = {'headers': {}, 'requestContext': {}}
        previous = os.environ.get(TRACE_ID_ENV_VAR)
        os.environ[TRACE_ID_ENV_VAR] = 'env-trace'
        try:
            self.assertEqual(extract_trace_id(event=event), 'env-trace')
        finally:
            if previous is None:
                del os.environ[TRACE_ID_ENV_VAR]
            else:
                os.environ[TRACE_ID_ENV_VAR] = previous

    def test_trace_id_wsgi_key_constant(self):
        # Applications read the trace from this non-standard environ key.
        self.assertEqual(TRACE_ID_WSGI_KEY, 'zappa.trace_id')
        self.assertEqual(TRACE_ID_HEADER, 'X-Zappa-Trace-Id')


if __name__ == '__main__':
    unittest.main()
