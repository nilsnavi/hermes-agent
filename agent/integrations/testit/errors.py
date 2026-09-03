"""Sanitized TestIT integration errors."""


class TestITError(RuntimeError):
    pass


class InvalidTestITConfiguration(TestITError):
    pass


class InvalidTestITIdentifier(TestITError):
    pass


class TestITUnavailable(TestITError):
    pass


class TestITAuthFailed(TestITError):
    pass


class TestITNotFound(TestITError):
    pass


class TestITRateLimited(TestITError):
    pass


class TestITUpstreamError(TestITError):
    pass
