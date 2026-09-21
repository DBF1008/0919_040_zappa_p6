import json
import logging
import os
import sys
import unittest
from unittest import mock

_STUBS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'stubs'))
if _STUBS not in sys.path:
    sys.path.insert(0, _STUBS)

from zappa import asynchronous
from zappa.observability import TRACE_ID_ENV_VAR


class ListHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class FakeLambdaAsyncResponse(asynchronous.LambdaAsyncResponse):
    def __init__(self):
        self.invocations = []
        self.capture_response = False
        self.response_id = None
        self.lambda_function_name = 'fn'
        self.aws_region = 'us-east-1'

    def _send(self, message):
        self.invocations.append(message)
        self.sent = True


class AsyncTracePropagationTests(unittest.TestCase):

    def setUp(self):
        self.previous_trace = os.environ.pop(TRACE_ID_ENV_VAR, None)
        self.handler = ListHandler()
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.INFO)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)
        if self.previous_trace is not None:
            os.environ[TRACE_ID_ENV_VAR] = self.previous_trace
        else:
            os.environ.pop(TRACE_ID_ENV_VAR, None)

    def test_lambda_async_send_includes_trace_id(self):
        os.environ[TRACE_ID_ENV_VAR] = 'origin-trace'
        sender = FakeLambdaAsyncResponse()
        sender.send('module.func', (1,), {'k': 'v'})
        self.assertEqual(len(sender.invocations), 1)
        message = sender.invocations[0]
        self.assertEqual(message['trace_id'], 'origin-trace')
        self.assertEqual(message['command'],
                         'zappa.asynchronous.route_lambda_task')

    def test_lambda_async_send_without_trace_id(self):
        sender = FakeLambdaAsyncResponse()
        sender.send('module.func', (), {})
        self.assertNotIn('trace_id', sender.invocations[0])

    def test_route_lambda_task_logs_with_propagated_trace(self):
        with mock.patch.object(asynchronous, 'run_message',
                               return_value='ok'):
            event = {
                'command': 'zappa.asynchronous.route_lambda_task',
                'task_path': 'module.func',
                'args': [],
                'kwargs': {},
                'trace_id': 'propagated-1',
            }
            result = asynchronous.route_lambda_task(event, None)
        self.assertEqual(result, 'ok')
        complete = [m for m in self.handler.messages
                    if '"event":"async.task.complete"' in m]
        self.assertEqual(len(complete), 1)
        decoded = json.loads(complete[0])
        self.assertEqual(decoded['trace_id'], 'propagated-1')
        self.assertEqual(decoded['outcome'], 'success')
        self.assertEqual(decoded['service'], 'lambda')

    def test_route_sns_task_logs_duration_on_failure(self):
        def boom(message):
            raise ValueError('task failed')

        with mock.patch.object(asynchronous, 'run_message', boom):
            event = {
                'Records': [{
                    'Sns': {'Message': json.dumps({
                        'task_path': 'module.bad',
                        'args': [],
                        'kwargs': {},
                        'trace_id': 'sns-trace',
                    })},
                }],
            }
            with self.assertRaises(ValueError):
                asynchronous.route_sns_task(event, None)

        complete = [m for m in self.handler.messages
                    if '"event":"async.task.complete"' in m]
        decoded = json.loads(complete[0])
        self.assertEqual(decoded['outcome'], 'failure')
        self.assertEqual(decoded['trace_id'], 'sns-trace')
        self.assertEqual(decoded['service'], 'sns')
        self.assertIn('task failed', decoded['error'])


if __name__ == '__main__':
    unittest.main()
