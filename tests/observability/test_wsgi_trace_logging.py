import collections
import json
import logging
import os
import sys
import unittest

# Allow the tests to run without the third-party `requestlogger` package
# installed by exposing the bundled compatibility stub first on sys.path.
_STUBS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'stubs'))
if _STUBS not in sys.path:
    sys.path.insert(0, _STUBS)

def parse_payload(access_line):
    part = access_line.split(' | ', 1)[1]
    part = part.split(' trace_id ', 1)[0]
    return json.loads(part)


from zappa.wsgi import common_log, create_wsgi_request
from zappa.observability import TRACE_ID_WSGI_KEY


def _sample_event(headers=None):
    return {
        'body': None,
        'resource': '/{proxy+}',
        'requestContext': {
            'resourceId': 'dg451y',
            'apiId': '79gqbxq31c',
            'resourcePath': '/{proxy+}',
            'httpMethod': 'GET',
            'requestId': '766df67f-8991-11e6-b2c4-d120fedb94e5',
            'identity': {'sourceIp': '96.90.37.59'},
            'stage': 'dev',
        },
        'queryStringParameters': None,
        'httpMethod': 'GET',
        'pathParameters': {'proxy': 'asdf1/asdf2'},
        'headers': headers or {
            'Host': '79gqbxq31c.execute-api.us-east-1.amazonaws.com',
            'X-Forwarded-For': '96.90.37.59, 54.240.144.50',
            'X-Forwarded-Proto': 'https',
        },
        'stageVariables': None,
        'path': '/asdf1/asdf2',
    }


class ListHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class WsgiTraceIdTests(unittest.TestCase):

    def test_trace_id_from_header_is_on_environ(self):
        event = _sample_event({'X-Zappa-Trace-Id': 'caller-trace'})
        environ = create_wsgi_request(event, trailing_slash=False)
        self.assertEqual(environ[TRACE_ID_WSGI_KEY], 'caller-trace')
        self.assertEqual(environ['HTTP_X_ZAPPA_TRACE_ID'], 'caller-trace')

    def test_trace_id_falls_back_to_api_gateway_request_id(self):
        environ = create_wsgi_request(_sample_event(), trailing_slash=False)
        self.assertEqual(environ[TRACE_ID_WSGI_KEY],
                         '766df67f-8991-11e6-b2c4-d120fedb94e5')

    def test_explicit_trace_id_argument_wins(self):
        event = _sample_event({'X-Zappa-Trace-Id': 'header-trace'})
        environ = create_wsgi_request(event, trailing_slash=False,
                                     trace_id='explicit-trace')
        self.assertEqual(environ[TRACE_ID_WSGI_KEY], 'explicit-trace')


class CommonLogTraceTests(unittest.TestCase):

    def setUp(self):
        self.root_logger = logging.getLogger()
        self.list_handler = ListHandler()
        self.root_logger.addHandler(self.list_handler)
        self.previous_level = self.root_logger.level
        self.root_logger.setLevel(logging.INFO)

    def tearDown(self):
        self.root_logger.removeHandler(self.list_handler)
        self.root_logger.setLevel(self.previous_level)

    def _log(self, **kwargs):
        environ = create_wsgi_request(_sample_event(), trailing_slash=False)
        response = collections.namedtuple(
            'Response', ['status_code', 'content'])(200, 'hello')
        return common_log(environ, response, **kwargs)

    def test_common_log_keeps_apache_prefix_for_tail_http_filter(self):
        entry = self._log(response_time=15.0, trace_id='t-1')
        first_token = entry.split(' ')[0]
        self.assertEqual(first_token.count('.'), 3)
        self.assertTrue(entry.split(' | ', 1)[0].startswith(
            '96.90.37.59'))

    def test_common_log_contains_structured_trace_payload(self):
        entry = self._log(response_time=15.0, trace_id='t-1')
        decoded = parse_payload(entry)
        self.assertEqual(decoded['trace_id'], 't-1')
        self.assertEqual(decoded['status_code'], 200)
        self.assertEqual(decoded['method'], 'GET')
        self.assertEqual(decoded['path'], '/asdf1/asdf2')
        self.assertEqual(decoded['response_time_ms'], 15.0)
        self.assertEqual(decoded['log_format'], 'zappa_access_v1')

    def test_common_log_uses_environ_trace_id_by_default(self):
        environ = create_wsgi_request(
            _sample_event({'X-Zappa-Trace-Id': 'environ-trace'}),
            trailing_slash=False)
        response = collections.namedtuple(
            'Response', ['status_code', 'content'])(204, '')
        entry = common_log(environ, response, response_time=1)
        self.assertEqual(
            parse_payload(entry)['trace_id'],
            'environ-trace')

    def test_common_log_without_response_time(self):
        entry = self._log(response_time=None, trace_id='t-2')
        decoded = parse_payload(entry)
        self.assertNotIn('response_time_ms', decoded)
        self.assertEqual(decoded['trace_id'], 't-2')

    def test_common_log_emits_info_record(self):
        self._log(response_time=1, trace_id='t-3')
        self.assertTrue(any('t-3' in message
                            for message in self.list_handler.messages))


if __name__ == '__main__':
    unittest.main()
