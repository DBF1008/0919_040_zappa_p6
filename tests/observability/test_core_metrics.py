import os
import sys
import unittest
from unittest import mock

_STUBS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'stubs'))
if _STUBS not in sys.path:
    sys.path.insert(0, _STUBS)


class CoreMetricsTests(unittest.TestCase):
    """Deployment metrics emitted from :class:`zappa.core.Zappa`."""

    def _build_zappa(self, enabled=True):
        # Import lazily: zappa.core pulls in a large dependency graph that is
        # only relevant for these tests.
        from zappa.core import Zappa

        boto_session = mock.MagicMock()
        cloudwatch = mock.MagicMock()
        boto_session.client.return_value = cloudwatch

        with mock.patch.object(Zappa, 'load_credentials'), \
                mock.patch.object(Zappa, 'boto_client',
                                  return_value=cloudwatch), \
                mock.patch.object(Zappa, 'boto_resource',
                                  return_value=mock.MagicMock()):
            zappa = Zappa(boto_session=boto_session,
                          aws_region='us-east-1',
                          load_credentials=True,
                          metrics_enabled=enabled)
        return zappa, cloudwatch

    def test_metrics_disabled_by_default(self):
        from zappa.core import Zappa

        boto_session = mock.MagicMock()
        with mock.patch.object(Zappa, 'load_credentials'), \
                mock.patch.object(Zappa, 'boto_client',
                                  return_value=mock.MagicMock()), \
                mock.patch.object(Zappa, 'boto_resource',
                                  return_value=mock.MagicMock()):
            zappa = Zappa(boto_session=boto_session,
                          aws_region='us-east-1',
                          load_credentials=True)
        self.assertFalse(zappa.metrics_enabled)
        self.assertFalse(zappa._metric_reporter.enabled)

    def test_update_lambda_function_reports_success(self):
        zappa, cloudwatch = self._build_zappa()
        cloudwatch.update_function_code.return_value = {
            'FunctionArn': 'arn:aws:lambda:us-east-1:1:function:fn',
            'Version': '1',
        }
        # get_alias must say the alias is missing.
        from botocore.exceptions import ClientError
        cloudwatch.get_alias.side_effect = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException'}}, 'GetAlias')

        arn = zappa.update_lambda_function(
            bucket='bkt', function_name='fn', s3_key='key.zip',
            publish=False)

        self.assertEqual(arn, 'arn:aws:lambda:us-east-1:1:function:fn')
        cloudwatch.put_metric_data.assert_called_once()
        kwargs = cloudwatch.put_metric_data.call_args[1]
        names = {d['MetricName'] for d in kwargs['MetricData']}
        self.assertEqual(names, {'DeploymentLatency', 'DeploymentSuccess'})
        for datum in kwargs['MetricData']:
            dimensions = {d['Name']: d['Value']
                          for d in datum['Dimensions']}
            self.assertEqual(dimensions['operation'],
                             'update_lambda_function')
            self.assertEqual(dimensions['function_name'], 'fn')

    def test_update_lambda_function_reports_failure(self):
        zappa, cloudwatch = self._build_zappa()
        from botocore.exceptions import ClientError
        cloudwatch.update_function_code.side_effect = ClientError(
            {'Error': {'Code': 'KMSAccessDeniedException'}},
            'UpdateFunctionCode')

        with self.assertRaises(ClientError):
            zappa.update_lambda_function(
                bucket='bkt', function_name='fn', s3_key='key.zip')

        kwargs = cloudwatch.put_metric_data.call_args[1]
        names = {d['MetricName'] for d in kwargs['MetricData']}
        self.assertEqual(names, {'DeploymentLatency', 'DeploymentFailure'})

    def test_deploy_api_gateway_reports_success(self):
        zappa, cloudwatch = self._build_zappa()
        cloudwatch.region_name = 'us-east-1'
        zappa.boto_session = mock.MagicMock()
        zappa.boto_session.region_name = 'us-east-1'

        url = zappa.deploy_api_gateway('api123', 'dev')

        self.assertIn('api123', url)
        self.assertIn('/dev', url)
        kwargs = cloudwatch.put_metric_data.call_args[1]
        names = {d['MetricName'] for d in kwargs['MetricData']}
        self.assertEqual(names, {'DeploymentLatency', 'DeploymentSuccess'})
        dimensions = {d['Name']: d['Value']
                      for d in kwargs['MetricData'][0]['Dimensions']}
        self.assertEqual(dimensions['operation'], 'deploy_api_gateway')
        self.assertEqual(dimensions['api_id'], 'api123')
        self.assertEqual(dimensions['stage'], 'dev')

    def test_deploy_api_gateway_reports_failure(self):
        zappa, cloudwatch = self._build_zappa()
        from botocore.exceptions import ClientError
        cloudwatch.create_deployment.side_effect = ClientError(
            {'Error': {'Code': 'BadRequestException'}}, 'CreateDeployment')

        with self.assertRaises(ClientError):
            zappa.deploy_api_gateway('api123', 'dev')

        names = {d['MetricName']
                 for d in cloudwatch.put_metric_data.call_args[1][
                     'MetricData']}
        self.assertEqual(names, {'DeploymentLatency', 'DeploymentFailure'})

    def test_upload_to_s3_reports_failure_for_missing_file(self):
        zappa, cloudwatch = self._build_zappa()
        result = zappa.upload_to_s3('/tmp/does-not-exist-xyz', 'bucket')
        self.assertFalse(result)
        kwargs = cloudwatch.put_metric_data.call_args[1]
        names = {d['MetricName'] for d in kwargs['MetricData']}
        self.assertEqual(names, {'DeploymentLatency', 'DeploymentFailure'})

    def test_metrics_namespace_is_configurable(self):
        from zappa.core import Zappa

        boto_session = mock.MagicMock()
        cloudwatch = mock.MagicMock()
        with mock.patch.object(Zappa, 'load_credentials'), \
                mock.patch.object(Zappa, 'boto_client',
                                  return_value=cloudwatch), \
                mock.patch.object(Zappa, 'boto_resource',
                                  return_value=mock.MagicMock()):
            zappa = Zappa(boto_session=boto_session,
                          aws_region='us-east-1',
                          load_credentials=True,
                          metrics_enabled=True,
                          metrics_namespace='Team/Deploy')
        self.assertEqual(zappa._metric_reporter.namespace, 'Team/Deploy')


if __name__ == '__main__':
    unittest.main()
