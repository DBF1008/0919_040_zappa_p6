class _ApiObject(object):
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class RestApi(_ApiObject):
    pass


class Resource(_ApiObject):
    pass


class Method(_ApiObject):
    pass


class Integration(_ApiObject):
    pass


class IntegrationResponse(_ApiObject):
    pass


class MethodResponse(_ApiObject):
    pass


class Authorizer(_ApiObject):
    pass


class EndpointConfiguration(_ApiObject):
    pass
