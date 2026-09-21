class Template(object):
    def __init__(self):
        pass

    def add_parameter(self, value):
        return value


class _BaseObject(object):
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def Ref(value):
    return ('ref', value)


def GetAtt(obj, attr):
    return ('getatt', obj, attr)


def Parameter(name, *args, **kwargs):
    return ('parameter', name)
