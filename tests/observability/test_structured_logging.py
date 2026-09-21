import json
import logging
import unittest

def parse_payload(access_line):
    part = access_line.split(' | ', 1)[1]
    part = part.split(' trace_id ', 1)[0]
    return json.loads(part)


from zappa.observability import build_access_log, log_event, render_structured


class ListHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def _looks_like_ip(token):
    # Mirror of ZappaCLI.is_http_log_entry token check.
    return token.count('.') == 3 and token.replace('.', '').isnumeric()


class RenderStructuredTests(unittest.TestCase):

    def test_single_line_sorted_json(self):
        rendered = render_structured({'b': 1, 'a': 'x'})
        self.assertEqual(rendered, '{"a":"x","b":1}')
        self.assertNotIn('\n', rendered)

    def test_non_serialisable_values_become_strings(self):
        rendered = render_structured({'when': object()})
        decoded = json.loads(rendered)
        self.assertIn('when', decoded)
        self.assertIsInstance(decoded['when'], str)


class LogEventTests(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger('test.observability.structured')
        self.handler = ListHandler()
        self.logger.addHandler(self.handler)
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous_level)

    def test_log_event_emits_json_with_trace_id(self):
        rendered = log_event(self.logger, 'demo.event',
                             trace_id='t-1', answer=42)
        decoded = json.loads(rendered)
        self.assertEqual(decoded['event'], 'demo.event')
        self.assertEqual(decoded['trace_id'], 't-1')
        self.assertEqual(decoded['answer'], 42)
        self.assertIn('timestamp', decoded)
        self.assertEqual(len(self.handler.records), 1)

    def test_log_event_without_trace_id(self):
        rendered = log_event(self.logger, 'no.trace')
        self.assertNotIn('trace_id', json.loads(rendered))

    def test_non_http_event_is_not_detected_as_http_log(self):
        rendered = log_event(self.logger, 'handler.invocation',
                             trace_id='abc')
        for token in rendered.replace('\t', ' ').split(' '):
            self.assertFalse(_looks_like_ip(token))


class AccessLogTests(unittest.TestCase):

    APACHE = ('127.0.0.1 - - [21/Sep/2026:00:00:00 +0000] '
              '"GET /health HTTP/1.1" 200 5 12.3ms')

    def test_access_log_keeps_apache_line_first(self):
        line = build_access_log(self.APACHE, trace_id='t-1')
        self.assertTrue(line.startswith('127.0.0.1 - - '))
        first_token = line.split(' ')[0]
        self.assertTrue(_looks_like_ip(first_token))

    def test_access_log_json_is_parseable(self):
        line = build_access_log(
            self.APACHE, trace_id='t-1', response_time_ms=12.3456,
            status_code=200, method='GET', path='/health')
        decoded = parse_payload(line)
        self.assertEqual(decoded['log_format'], 'zappa_access_v1')
        self.assertEqual(decoded['trace_id'], 't-1')
        self.assertEqual(decoded['response_time_ms'], 12.346)
        self.assertEqual(decoded['status_code'], 200)
        self.assertEqual(decoded['method'], 'GET')
        self.assertEqual(decoded['path'], '/health')

    def test_access_log_without_optional_fields(self):
        line = build_access_log(self.APACHE)
        decoded = parse_payload(line)
        self.assertNotIn('trace_id', decoded)
        self.assertNotIn('status_code', decoded)

    def test_extra_fields_are_merged(self):
        line = build_access_log(self.APACHE, trace_id='t-1',
                                stage='dev', request_id='r-9')
        decoded = parse_payload(line)
        self.assertEqual(decoded['stage'], 'dev')
        self.assertEqual(decoded['request_id'], 'r-9')


if __name__ == '__main__':
    unittest.main()
