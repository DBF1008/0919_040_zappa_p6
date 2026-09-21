try:
    from unittest.mock import MagicMock, patch, Mock
except ImportError:  # pragma: no cover
    raise ImportError('unittest.mock is required on Python 3')
