def tqdm(*args, **kwargs):
    class _Bar(object):
        def update(self, value):
            pass

        def close(self):
            pass
    return _Bar()
