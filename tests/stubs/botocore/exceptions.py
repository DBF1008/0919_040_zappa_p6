class ClientError(Exception):
    def __init__(self, error_response, operation_name):
        self.response = error_response
        self.operation_name = operation_name
        super(ClientError, self).__init__(str(error_response))


class NoRegionError(Exception):
    pass


class ParamValidationError(Exception):
    pass


class BotoCoreError(Exception):
    pass
