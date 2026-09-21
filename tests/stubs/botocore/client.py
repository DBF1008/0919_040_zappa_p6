class Config(object):
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)
