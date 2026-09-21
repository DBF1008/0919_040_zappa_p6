"""
Minimal stand-in for the third-party ``requestlogger`` package.

Only used when the real dependency is not installed (e.g. running the
observability test-suite in an environment without the full Zappa
requirements). The output mirrors the Apache Common Log Format prefix that
``zappa tail`` parses: ``<remote-ip> - - ... "<method> <path> HTTP/1.1"``.
"""

try:
    from time import strftime, gmtime
except ImportError:  # pragma: no cover
    strftime = gmtime = None


class ApacheFormatter(object):
    def __init__(self, with_response_time=False):
        self.with_response_time = with_response_time

    def __call__(self, status_code, environ, content_length,
                 rt_us=None, rt_ms=None):
        line = '{remote} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {length}'.format(
            remote=environ.get('REMOTE_ADDR', '-'),
            stamp=strftime('%d/%b/%Y:%H:%M:%S +0000', gmtime()),
            method=environ.get('REQUEST_METHOD', '-'),
            path=environ.get('PATH_INFO', '/'),
            status=status_code,
            length=content_length,
        )
        if self.with_response_time:
            value = rt_us if rt_us is not None else rt_ms
            line = '{0} {1}'.format(line, value)
        return line
