import json
import logging
import unittest

from zappa.observability import DEFAULT_NAMESPACE, MetricReporter, Timer


class FakeCloudWatchClient(object):
    def __init__(self, raise_exc=None):
        self.calls = []
        self.raise_exc = raise_exc

    def put_metric_data(self, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        self.calls.append(kwargs)


class MetricReporterTests(unittest.TestCase):

    def test_disabled_reporter_is_noop(self):
        reporter = MetricReporter(
            cloudwatch_client=FakeCloudWatchClient(), enabled=False)
        reporter.add_metric('x', 1)
        reporter.record_latency('y', 2)
        self.assertEqual(reporter.datums, [])
        self.assertEqual(reporter.flush(), 0)

    def test_default_namespace(self):
        self.assertEqual(DEFAULT_NAMESPACE, 'Zappa/Observability')

    def test_add_metric_builds_datum(self):
        reporter = MetricReporter(enabled=True)
        reporter.add_metric('simple', 3, unit='Count',
                            dimensions={'operation': 'upload_to_s3'})
        datums = reporter.datums
        self.assertEqual(len(datums), 1)
        self.assertEqual(datums[0]['MetricName'], 'simple')
        self.assertEqual(datums[0]['Value'], 3.0)
        self.assertEqual(datums[0]['Unit'], 'Count')
        self.assertEqual(datums[0]['Dimensions'],
                         [{'Name': 'operation', 'Value': 'upload_to_s3'}])

    def test_none_dimension_values_are_skipped(self):
        reporter = MetricReporter(
            enabled=True,
            default_dimensions={'project': None, 'stage': 'dev'})
        reporter.add_metric('x', 1, dimensions={'bucket': None})
        self.assertEqual(reporter.datums[0]['Dimensions'],
                         [{'Name': 'stage', 'Value': 'dev'}])

    def test_non_numeric_values_are_ignored(self):
        reporter = MetricReporter(enabled=True)
        reporter.add_metric('bad', 'not-a-number')
        self.assertEqual(reporter.datums, [])

    def test_flush_without_client_clears_buffer(self):
        reporter = MetricReporter(cloudwatch_client=None, enabled=True)
        reporter.record_count('c')
        self.assertEqual(reporter.flush(), 1)
        self.assertEqual(reporter.datums, [])

    def test_flush_calls_cloudwatch(self):
        client = FakeCloudWatchClient()
        reporter = MetricReporter(cloudwatch_client=client, enabled=True,
                                  namespace='Custom/NS')
        reporter.record_latency('DeploymentLatency', 12.5,
                                dimensions={'operation': 'deploy_api_gateway'})
        flushed = reporter.flush()
        self.assertEqual(flushed, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]['Namespace'], 'Custom/NS')
        datum = client.calls[0]['MetricData'][0]
        self.assertEqual(datum['MetricName'], 'DeploymentLatency')
        self.assertEqual(datum['Unit'], 'Milliseconds')

    def test_flush_swallows_client_errors(self):
        client = FakeCloudWatchClient(raise_exc=RuntimeError('denied'))
        reporter = MetricReporter(cloudwatch_client=client, enabled=True)
        reporter.record_count('c')
        # Must not raise.
        self.assertEqual(reporter.flush(), 0)
        self.assertEqual(reporter.datums, [])

    def test_batch_auto_flushes_at_20(self):
        client = FakeCloudWatchClient()
        reporter = MetricReporter(cloudwatch_client=client, enabled=True)
        for index in range(20):
            reporter.record_count('m{}'.format(index))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(client.calls[0]['MetricData']), 20)


class TimerTests(unittest.TestCase):

    def test_success_timer_records_latency_and_success_count(self):
        client = FakeCloudWatchClient()
        reporter = MetricReporter(cloudwatch_client=client, enabled=True)
        with Timer('op.one', reporter, trace_id='t-1') as timer:
            pass
        self.assertIsNotNone(timer.elapsed_ms)
        self.assertTrue(timer.succeeded)
        names = sorted(d['MetricName'] for d in reporter.datums)
        self.assertEqual(names, ['op.one', 'op.one.Success'])
        reporter.flush()
        self.assertEqual(client.calls[0]['MetricData'][0]['Unit'],
                         'Milliseconds')

    def test_failure_timer_records_failure_and_reraises(self):
        reporter = MetricReporter(cloudwatch_client=None, enabled=True)
        with self.assertRaises(ValueError):
            with Timer('op.two', reporter, trace_id='t-2'):
                raise ValueError('boom')
        names = sorted(d['MetricName'] for d in reporter.datums)
        self.assertEqual(names, ['op.two', 'op.two.Failure'])

    def test_timer_emits_structured_log(self):
        records = []

        class H(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        target = logging.getLogger('test.timer')
        handler = H()
        target.addHandler(handler)
        target.setLevel(logging.DEBUG)
        try:
            with Timer('op.three', trace_id='t-3', logger=target):
                pass
        finally:
            target.removeHandler(handler)

        decoded = json.loads(records[0])
        self.assertEqual(decoded['event'], 'timing.op.three')
        self.assertEqual(decoded['trace_id'], 't-3')
        self.assertEqual(decoded['outcome'], 'success')
        self.assertIn('duration_ms', decoded)

    def test_timer_works_as_decorator(self):
        reporter = MetricReporter(enabled=True)

        @Timer('decorated', reporter)
        def add(a, b):
            return a + b

        self.assertEqual(add(1, 2), 3)
        self.assertTrue(any(d['MetricName'] == 'decorated.Success'
                            for d in reporter.datums))


if __name__ == '__main__':
    unittest.main()
