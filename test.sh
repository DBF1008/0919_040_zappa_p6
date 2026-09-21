#!/usr/bin/env bash
#
# Zappa unit-test runner.
#
# Usage:
#   ./test.sh                 # run every unit-test module below
#   ./test.sh <module>        # run a single module, e.g.
#                             # ./test.sh tests.test_handler
#   ./test.sh observability   # run only the new observability suite
#
# All unit-test scripts can also be run individually by hand:
#   nosetests tests.test_handler -s
#   python3 -m pytest tests/observability -v
#
set -euo pipefail
cd "$(dirname "$0")"

# Find a Python interpreter that actually has pytest installed. The active
# shell may expose a virtualenv without the project's test dependencies.
PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3 python /opt/homebrew/bin/python3.10 /usr/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
           && "$candidate" -c "import pytest" >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "No Python interpreter with pytest found." >&2
    echo "Install test dependencies with: pip install -r test_requirements.txt" >&2
    exit 1
fi

if [ "$#" -ge 1 ]; then
    TARGET="$1"
else
    TARGET="all"
fi

run_nose() {
    if command -v nosetests >/dev/null 2>&1; then
        nosetests "$@"
    else
        echo "nosetests not found; falling back to pytest" >&2
        "$PYTHON_BIN" -m pytest "${@//./\/}.py"
    fi
}

case "$TARGET" in
    all)
        echo "== Running full unit-test suite =="
        # New observability suite: structured logging, request tracing and
        # custom CloudWatch metrics.
        "$PYTHON_BIN" -m pytest tests/observability -v
        # Classic Zappa unit-test scripts.
        for module in \
            tests.test_handler \
            tests.test_app \
            tests.tests \
            tests.tests_async \
            tests.tests_async_old \
            tests.tests_middleware \
            tests.tests_placebo \
            tests.tests_docs \
            tests.test_bot_exception_handler_settings \
            tests.test_bot_handler_being_triggered \
            tests.test_event_script_app \
            tests.test_event_script_settings \
            tests.test_exception_handler_settings \
            tests.test_wsgi_script_name_app \
            tests.test_wsgi_script_name_settings \
            ; do
            echo "== $module =="
            run_nose "$module"
        done
        ;;
    observability)
        "$PYTHON_BIN" -m pytest tests/observability -v
        ;;
    *)
        run_nose "$TARGET"
        ;;
esac

echo ""
echo "Individual manual commands:"
echo "  nosetests tests.test_handler -s"
echo "  nosetests tests.tests:TestZappa.test_wsgi_logging -s"
echo "  $PYTHON_BIN -m pytest tests/observability/test_tracing.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_structured_logging.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_metrics.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_wsgi_trace_logging.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_handler_observability.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_async_propagation.py -v"
echo "  $PYTHON_BIN -m pytest tests/observability/test_core_metrics.py -v"
