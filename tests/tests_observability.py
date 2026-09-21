# -*- coding: utf8 -*-
"""
Unit tests for the observability features: structured logging,
request tracing and custom CloudWatch metrics.
"""
import collections
import logging
import os
import tempfile
import unittest
import uuid

import mock

from zappa.observability import (format_structured, generate_trace_id,
                                 get_trace_id, log_structured,
                                 put_custom_metric, timer)
from zappa.wsgi import create_wsgi_request, common_log
from zappa.core import Zappa
from zappa.handler import LambdaHandler


def dummy_task(event, context):
    """Target for async dispatch tests."""
    return 'done'


def build_api_gateway_event(headers=None, request_context=None):
    return {
        'body': '',
        'resource': '/{proxy+}',
        'requestContext': request_context or {},
        'queryStringParameters': {},
        'headers': headers or {'Host': 'example.com'},
        'pathParameters': {'proxy': 'return/request/url'},
        'httpMethod': 'GET',
        'stageVariables': {},
        'path': '/return/request/url'
    }


class TestTraceId(unittest.TestCase):

    def test_generate_trace_id_is_uuid(self):
        trace_id = generate_trace_id()
        # Raises ValueError if not a valid UUID.
        self.assertEqual(str(uuid.UUID(trace_id)), trace_id)

    def test_trace_id_from_event_header(self):
        event = build_api_gateway_event(headers={'X-Trace-Id': 'trace-from-header'})
        self.assertEqual(get_trace_id(event=event), 'trace-from-header')

    def test_trace_id_from_amzn_header(self):
        event = build_api_gateway_event(headers={'X-Amzn-Trace-Id': 'Root=1-abc'})
        self.assertEqual(get_trace_id(event=event), 'Root=1-abc')

    def test_trace_id_from_request_context(self):
        event = build_api_gateway_event(
            request_context={'requestId': 'req-1234'})
        self.assertEqual(get_trace_id(event=event), 'req-1234')

    def test_trace_id_from_lambda_context(self):
        context = mock.Mock()
        context.aws_request_id = 'lambda-req-5678'
        self.assertEqual(get_trace_id(context=context), 'lambda-req-5678')

    def test_trace_id_generated_when_missing(self):
        trace_id = get_trace_id(event={}, context=None)
        self.assertEqual(str(uuid.UUID(trace_id)), trace_id)

    def test_trace_id_from_environ(self):
        environ = {'HTTP_X_TRACE_ID': 'env-trace'}
        self.assertEqual(get_trace_id(environ=environ), 'env-trace')

    def test_environ_trace_id_wins(self):
        environ = {'zappa.trace_id': 'existing', 'HTTP_X_TRACE_ID': 'other'}
        self.assertEqual(get_trace_id(environ=environ), 'existing')

    def test_header_beats_request_context(self):
        event = build_api_gateway_event(
            headers={'X-Trace-Id': 'from-header'},
            request_context={'requestId': 'from-context'})
        self.assertEqual(get_trace_id(event=event), 'from-header')


class TestStructuredLogging(unittest.TestCase):

    def test_format_structured_key_value(self):
        line = format_structured('zappa.request', trace_id='abc', status=200)
        self.assertEqual(line, 'zappa.request status=200 trace_id=abc')

    def test_format_structured_quotes_whitespace(self):
        line = format_structured('msg', path='/hello world')
        self.assertEqual(line, 'msg path="/hello world"')

    def test_format_structured_skips_none(self):
        line = format_structured('msg', function=None, duration_ms=1.5)
        self.assertEqual(line, 'msg duration_ms=1.5')

    def test_log_structured_emits_single_line(self):
        with self.assertLogs(level='INFO') as captured:
            log_structured(logging.INFO, 'zappa.test', trace_id='t1')
        self.assertEqual(len(captured.output), 1)
        self.assertIn('zappa.test trace_id=t1', captured.output[0])

    def test_timer_measures_duration(self):
        with timer() as t:
            sum(range(1000))
        self.assertIsNotNone(t.duration_ms)
        self.assertGreaterEqual(t.duration_ms, 0)


class TestWsgiTracing(unittest.TestCase):

    def _make_response(self):
        response_tuple = collections.namedtuple('Response', ['status_code', 'content'])
        return response_tuple(200, 'hello')

    def test_create_wsgi_request_sets_trace_id(self):
        event = build_api_gateway_event(headers={'X-Trace-Id': 'wsgi-trace'})
        environ = create_wsgi_request(event, trailing_slash=False)
        self.assertEqual(environ['zappa.trace_id'], 'wsgi-trace')

    def test_create_wsgi_request_generates_trace_id(self):
        event = build_api_gateway_event()
        environ = create_wsgi_request(event, trailing_slash=False)
        self.assertEqual(str(uuid.UUID(environ['zappa.trace_id'])),
                         environ['zappa.trace_id'])

    def test_common_log_includes_trace_id(self):
        event = build_api_gateway_event(headers={'X-Trace-Id': 'log-trace'})
        environ = create_wsgi_request(event, trailing_slash=False)
        log_entry = common_log(environ, self._make_response(),
                               response_time=12.5)
        self.assertIn('trace_id=log-trace', log_entry)

    def test_common_log_keeps_apache_format(self):
        """
        The Apache Common Log Format prefix must stay intact so that
        `zappa tail` keeps detecting these lines as HTTP log entries
        (it looks for the client IP token).
        """
        event = build_api_gateway_event()
        environ = create_wsgi_request(event, trailing_slash=False)
        log_entry = common_log(environ, self._make_response(),
                               response_time=12.5)
        first_token = log_entry.split(' ')[0]
        # Client IP is still the first token (Apache format).
        self.assertEqual(first_token.count('.'), 3)
        self.assertTrue(first_token.replace('.', '').isnumeric())
        # Trace id is only appended as a key=value suffix.
        self.assertIn(' trace_id=', log_entry)
        self.assertIn('"GET /return/request/url', log_entry)

    def test_common_log_without_response_time(self):
        event = build_api_gateway_event()
        environ = create_wsgi_request(event, trailing_slash=False)
        log_entry = common_log(environ, self._make_response())
        self.assertIn(' trace_id=', log_entry)


class TestCloudWatchMetrics(unittest.TestCase):

    def setUp(self):
        os.environ.pop('ZAPPA_DISABLE_METRICS', None)

    def tearDown(self):
        os.environ.pop('ZAPPA_DISABLE_METRICS', None)

    def _metric_names(self, cloudwatch_client):
        return [call[1]['MetricData'][0]['MetricName']
                for call in cloudwatch_client.put_metric_data.call_args_list]

    def test_put_custom_metric(self):
        client = mock.Mock()
        result = put_custom_metric(client, 'MyMetric', 42,
                                   unit='Milliseconds',
                                   dimensions={'Operation': 'Deploy'})
        self.assertTrue(result)
        client.put_metric_data.assert_called_once_with(
            Namespace='Zappa',
            MetricData=[{
                'MetricName': 'MyMetric',
                'Value': 42,
                'Unit': 'Milliseconds',
                'Dimensions': [{'Name': 'Operation', 'Value': 'Deploy'}],
            }]
        )

    def test_put_custom_metric_custom_namespace(self):
        client = mock.Mock()
        put_custom_metric(client, 'MyMetric', 1, namespace='MyApp')
        self.assertEqual(client.put_metric_data.call_args[1]['Namespace'],
                         'MyApp')

    def test_put_custom_metric_disabled_by_env(self):
        os.environ['ZAPPA_DISABLE_METRICS'] = '1'
        client = mock.Mock()
        result = put_custom_metric(client, 'MyMetric', 1)
        self.assertFalse(result)
        client.put_metric_data.assert_not_called()

    def test_put_custom_metric_no_client(self):
        self.assertFalse(put_custom_metric(None, 'MyMetric', 1))

    def test_put_custom_metric_never_raises(self):
        client = mock.Mock()
        client.put_metric_data.side_effect = Exception('boom')
        self.assertFalse(put_custom_metric(client, 'MyMetric', 1))

    def _make_zappa(self):
        zappa = Zappa(boto_session=mock.Mock(), aws_region='us-east-1',
                      load_credentials=False)
        zappa.boto_session = mock.Mock()
        zappa.boto_session.region_name = 'us-east-1'
        zappa.s3_client = mock.Mock()
        zappa.lambda_client = mock.Mock()
        zappa.apigateway_client = mock.Mock()
        zappa.cloudwatch = mock.Mock()
        return zappa

    def test_upload_to_s3_reports_success_metrics(self):
        zappa = self._make_zappa()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b'zip-content')
            source_path = tmp.name
        try:
            result = zappa.upload_to_s3(source_path, 'my-bucket',
                                        disable_progress=True)
        finally:
            os.unlink(source_path)
        self.assertTrue(result)
        metric_names = self._metric_names(zappa.cloudwatch)
        self.assertIn('OperationLatency', metric_names)
        self.assertIn('OperationSuccess', metric_names)
        self.assertNotIn('OperationFailure', metric_names)
        # Dimensions carry the operation name.
        for call in zappa.cloudwatch.put_metric_data.call_args_list:
            self.assertEqual(call[1]['Namespace'], 'Zappa')
            self.assertEqual(call[1]['MetricData'][0]['Dimensions'],
                             [{'Name': 'Operation', 'Value': 'UploadToS3'}])

    def test_upload_to_s3_reports_failure_metrics(self):
        zappa = self._make_zappa()
        result = zappa.upload_to_s3('/nonexistent/file.zip', 'my-bucket',
                                    disable_progress=True)
        self.assertFalse(result)
        metric_names = self._metric_names(zappa.cloudwatch)
        self.assertIn('OperationFailure', metric_names)
        self.assertNotIn('OperationSuccess', metric_names)

    def test_update_lambda_function_reports_metrics(self):
        zappa = self._make_zappa()
        zappa.lambda_client.update_function_code.return_value = {
            'FunctionArn': 'arn:aws:lambda:us-east-1:1:function:f',
            'Version': '1',
        }
        zappa.lambda_client.get_alias.return_value = {}
        arn = zappa.update_lambda_function('bucket', 'function')
        self.assertEqual(arn, 'arn:aws:lambda:us-east-1:1:function:f')
        metric_names = self._metric_names(zappa.cloudwatch)
        self.assertIn('OperationLatency', metric_names)
        self.assertIn('OperationSuccess', metric_names)
        for call in zappa.cloudwatch.put_metric_data.call_args_list:
            self.assertEqual(
                call[1]['MetricData'][0]['Dimensions'],
                [{'Name': 'Operation', 'Value': 'UpdateLambdaFunction'}])

    def test_update_lambda_function_reports_failure_on_exception(self):
        zappa = self._make_zappa()
        zappa.lambda_client.update_function_code.side_effect = Exception('aws error')
        with self.assertRaises(Exception):
            zappa.update_lambda_function('bucket', 'function')
        metric_names = self._metric_names(zappa.cloudwatch)
        self.assertIn('OperationFailure', metric_names)

    def test_deploy_api_gateway_reports_metrics(self):
        zappa = self._make_zappa()
        url = zappa.deploy_api_gateway('api-id', 'stage')
        self.assertEqual(
            url, 'https://api-id.execute-api.us-east-1.amazonaws.com/stage')
        metric_names = self._metric_names(zappa.cloudwatch)
        self.assertIn('OperationLatency', metric_names)
        self.assertIn('OperationSuccess', metric_names)
        for call in zappa.cloudwatch.put_metric_data.call_args_list:
            self.assertEqual(
                call[1]['MetricData'][0]['Dimensions'],
                [{'Name': 'Operation', 'Value': 'DeployApiGateway'}])

    def test_metrics_disabled_skips_operation_metrics(self):
        os.environ['ZAPPA_DISABLE_METRICS'] = 'true'
        zappa = self._make_zappa()
        zappa.deploy_api_gateway('api-id', 'stage')
        zappa.cloudwatch.put_metric_data.assert_not_called()


class TestHandlerObservability(unittest.TestCase):

    def tearDown(self):
        LambdaHandler._LambdaHandler__instance = None
        LambdaHandler.settings = None
        LambdaHandler.settings_name = None

    def test_wsgi_request_logs_timing_and_trace_id(self):
        lh = LambdaHandler('tests.test_wsgi_script_name_settings')
        event = build_api_gateway_event(headers={
            'Host': 'example.com',
            'X-Trace-Id': 'handler-trace-1',
        })
        with self.assertLogs(level='INFO') as captured:
            response = lh.handler(event, None)
        self.assertEqual(response['statusCode'], 200)

        output = '\n'.join(captured.output)
        # The structured request log carries the trace id and timings.
        self.assertIn('zappa.request', output)
        self.assertIn('trace_id=handler-trace-1', output)
        self.assertIn('wsgi_duration_ms=', output)
        self.assertIn('total_duration_ms=', output)
        # The Apache access log for the same request carries the
        # same trace id, so both can be correlated.
        apache_lines = [line for line in captured.output
                        if '"GET /return/request/url' in line]
        self.assertTrue(apache_lines)
        self.assertIn('trace_id=handler-trace-1', apache_lines[0])

    def test_async_dispatch_logs_duration(self):
        lh = LambdaHandler('tests.test_wsgi_script_name_settings')
        event = {
            'command': 'tests.tests_observability.dummy_task',
        }
        with self.assertLogs(level='INFO') as captured:
            result = lh.handler(event, None)
        self.assertEqual(result, 'done')
        output = '\n'.join(captured.output)
        self.assertIn('zappa.dispatch', output)
        self.assertIn('dispatch_type=async', output)
        self.assertIn('function=tests.tests_observability.dummy_task', output)
        self.assertIn('duration_ms=', output)
        self.assertIn('trace_id=', output)

    def test_dispatch_uses_lambda_request_id_as_trace_id(self):
        lh = LambdaHandler('tests.test_wsgi_script_name_settings')
        context = mock.Mock()
        context.aws_request_id = 'lambda-trace-9'
        event = {'command': 'tests.tests_observability.dummy_task'}
        with self.assertLogs(level='INFO') as captured:
            lh.handler(event, context)
        output = '\n'.join(captured.output)
        self.assertIn('trace_id=lambda-trace-9', output)


if __name__ == '__main__':
    unittest.main()
