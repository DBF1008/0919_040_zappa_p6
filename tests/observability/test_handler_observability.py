import json
import logging
import os
import sys
import unittest

# Compatibility stubs for environments without the full AWS test stack
# (boto3/botocore/requestlogger/mock). No-op when the real packages exist.
_STUBS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'stubs'))
if _STUBS not in sys.path:
    sys.path.insert(0, _STUBS)

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

def parse_payload(access_line):
    part = access_line.split(' | ', 1)[1]
    part = part.split(' trace_id ', 1)[0]
    return json.loads(part)


from zappa.handler import LambdaHandler
from zappa.observability import TRACE_ID_ENV_VAR, MetricReporter


class ListHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


SETTINGS = 'tests.test_wsgi_script_name_settings'


class CapturingCloudWatch(object):
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


def http_event(headers=None, request_id=None):
    context = {}
    if request_id:
        context['requestId'] = request_id
    return {
        'body': '',
        'resource': '/{proxy+}',
        'requestContext': context,
        'queryStringParameters': {},
        'headers': headers or {
            'Host': '1234567890.execute-api.us-east-1.amazonaws.com',
        },
        'pathParameters': {'proxy': 'return/request/url'},
        'httpMethod': 'GET',
        'stageVariables': {},
        'path': '/return/request/url',
    }


class HandlerObservabilityTests(unittest.TestCase):

    def setUp(self):
        self.cloudwatch = CapturingCloudWatch()
        self.log_handler = ListHandler()
        self.root_logger = logging.getLogger()
        self.root_logger.addHandler(self.log_handler)
        self.previous_level = self.root_logger.level
        self.root_logger.setLevel(logging.INFO)
        self.previous_trace = os.environ.pop(TRACE_ID_ENV_VAR, None)

    def tearDown(self):
        self.root_logger.removeHandler(self.log_handler)
        self.root_logger.setLevel(self.previous_level)
        if self.previous_trace is not None:
            os.environ[TRACE_ID_ENV_VAR] = self.previous_trace
        else:
            os.environ.pop(TRACE_ID_ENV_VAR, None)
        LambdaHandler._LambdaHandler__instance = None
        LambdaHandler.settings = None
        LambdaHandler.settings_name = None
        LambdaHandler.metric_reporter = None

    def make_handler(self, settings=SETTINGS):
        handler = LambdaHandler(settings)
        handler.metric_reporter = MetricReporter(
            cloudwatch_client=self.cloudwatch, enabled=True,
            default_dimensions={'stage': 'dev'})
        return handler

    def test_http_request_emits_trace_access_log_and_metrics(self):
        handler = self.make_handler()
        event = http_event(headers={
            'Host': '1234567890.execute-api.us-east-1.amazonaws.com',
            'X-Zappa-Trace-Id': 'trace-xyz',
        })

        response = handler.handler(event, None)
        self.assertEqual(response['statusCode'], 200)

        # Trace id propagated into the environment (async tasks reuse it).
        self.assertEqual(os.environ.get(TRACE_ID_ENV_VAR), 'trace-xyz')

        # An Apache-prefixed access log line with the structured trace
        # payload was emitted (zappa tail --http compatible).
        access_lines = [m for m in self.log_handler.messages
                        if 'GET /return/request/url' in m
                        and 'zappa_access_v1' in m]
        self.assertEqual(len(access_lines), 1)
        payload = parse_payload(access_lines[0])
        self.assertEqual(payload['trace_id'], 'trace-xyz')
        self.assertEqual(payload['status_code'], 200)
        self.assertIn('response_time_ms', payload)

        # Structured invocation + response events share the same trace id.
        invocation = [m for m in self.log_handler.messages
                      if '"event":"handler.invocation"' in m]
        self.assertTrue(invocation)
        self.assertIn('trace-xyz', invocation[0])
        http_response = [m for m in self.log_handler.messages
                         if '"event":"http.response"' in m]
        self.assertTrue(http_response)

        # Metrics were flushed to CloudWatch.
        self.assertEqual(len(self.cloudwatch.calls), 1)
        names = {d['MetricName']
                 for d in self.cloudwatch.calls[0]['MetricData']}
        self.assertIn('event.route', names)
        self.assertIn('event.route.Success', names)
        self.assertIn('wsgi.request', names)
        self.assertIn('wsgi.request.Success', names)
        self.assertIn('http.status_code', names)

    def test_http_request_without_trace_header_uses_generated_id(self):
        handler = self.make_handler()
        response = handler.handler(http_event(request_id='gw-123'), None)
        self.assertEqual(response['statusCode'], 200)
        # API Gateway requestId is used as trace id.
        self.assertEqual(os.environ.get(TRACE_ID_ENV_VAR), 'gw-123')

    def test_command_invocation_is_timed(self):
        handler = self.make_handler()
        event = {'command': 'tests.test_handler.no_args'}
        handler.handler(event, None)
        names = {d['MetricName']
                 for d in self.cloudwatch.calls[0]['MetricData']}
        self.assertIn('event.command', names)
        self.assertIn('event.command.Success', names)
        timing = [m for m in self.log_handler.messages
                  if '"event":"timing.event.command"' in m]
        self.assertEqual(len(timing), 1)
        decoded = json.loads(timing[0])
        self.assertEqual(decoded['outcome'], 'success')

    def test_async_command_propagates_trace_id(self):
        handler = self.make_handler()
        event = {
            'command': 'tests.test_handler.no_args',
            'trace_id': 'async-trace-1',
        }
        handler.handler(event, None)
        self.assertEqual(os.environ.get(TRACE_ID_ENV_VAR), 'async-trace-1')
        timing = [m for m in self.log_handler.messages
                  if 'async-trace-1' in m]
        self.assertTrue(timing)

    def test_failing_request_records_failure_metric(self):
        handler = self.make_handler('tests.test_exception_handler_settings')
        event = http_event()
        response = handler.handler(event, None)
        self.assertEqual(response['statusCode'], 500)
        error_logs = [m for m in self.log_handler.messages
                      if '"event":"handler.error"' in m]
        self.assertTrue(error_logs)
        decoded = json.loads(error_logs[0])
        self.assertEqual(decoded['error_type'], 'Exception')

    def test_wsgi_request_timer_reports_failure_on_app_exception(self):
        # Force Response.from_app to fail; the WSGI timer must record Failure
        # rather than swallow the exception (the outer handler still turns it
        # into a 500 response).
        handler = self.make_handler('tests.test_exception_handler_settings')
        with mock.patch('zappa.handler.Response') as response_cls:
            response_cls.from_app.side_effect = RuntimeError('wsgi boom')
            response = handler.handler(http_event(), None)
        self.assertEqual(response['statusCode'], 500)
        failure_names = [d['MetricName']
                         for call in self.cloudwatch.calls
                         for d in call['MetricData']
                         if d['MetricName'].endswith('.Failure')]
        self.assertTrue(any(name in ('wsgi.request.Failure',
                                     'event.route.Failure')
                            for name in failure_names))


if __name__ == '__main__':
    unittest.main()
