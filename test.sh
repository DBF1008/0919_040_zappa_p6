#! /bin/bash
# Run all Zappa unit tests.
#
# Custom CloudWatch metrics are disabled during the test run so that
# no metric calls are made against real AWS endpoints.
export ZAPPA_DISABLE_METRICS=1

# Full suite with coverage:
nosetests --with-coverage --cover-package=zappa

# Individual test modules (for manual, focused runs):
# nosetests tests.tests -s
# nosetests tests.tests_async -s
# nosetests tests.tests_async_old -s
# nosetests tests.tests_docs -s
# nosetests tests.tests_middleware -s
# nosetests tests.tests_placebo -s
# nosetests tests.test_handler -s
# nosetests tests.tests_observability -s

# For a specific test:
# nosetests tests.tests:TestZappa.test_lets_encrypt_sanity -s
# nosetests tests.tests_observability:TestCloudWatchMetrics.test_upload_to_s3_reports_success_metrics -s
