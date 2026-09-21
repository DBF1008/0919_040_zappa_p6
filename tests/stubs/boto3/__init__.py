class _GenericClient(object):
    """Permissive stand-in for any boto3 service client."""

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            return {}
        return _method


class Session(object):
    def __init__(self, *args, **kwargs):
        pass

    def client(self, name, *args, **kwargs):
        return _GenericClient()

    def resource(self, name, *args, **kwargs):
        return _GenericClient()
