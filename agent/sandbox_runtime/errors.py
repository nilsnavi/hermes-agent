"""Stable, redacted sandbox mutation error taxonomy."""
from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import Enum


class CanonicalErrorCode(str, Enum):
    NO_SPACE = "NO_SPACE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    READ_ONLY_FILESYSTEM = "READ_ONLY_FILESYSTEM"
    TIMEOUT = "TIMEOUT"
    IO_ERROR = "IO_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CanonicalError:
    code: CanonicalErrorCode
    message: str
    retryable: bool = False


_ERRNO_CODES = {
    errno.ENOSPC: CanonicalErrorCode.NO_SPACE,
    errno.EACCES: CanonicalErrorCode.PERMISSION_DENIED,
    errno.EPERM: CanonicalErrorCode.PERMISSION_DENIED,
    errno.EROFS: CanonicalErrorCode.READ_ONLY_FILESYSTEM,
    errno.ETIMEDOUT: CanonicalErrorCode.TIMEOUT,
}
_MESSAGES = {
    CanonicalErrorCode.NO_SPACE: "storage capacity exhausted",
    CanonicalErrorCode.PERMISSION_DENIED: "operation not permitted",
    CanonicalErrorCode.READ_ONLY_FILESYSTEM: "filesystem is read-only",
    CanonicalErrorCode.TIMEOUT: "operation timed out",
    CanonicalErrorCode.IO_ERROR: "input/output operation failed",
    CanonicalErrorCode.UNKNOWN: "operation failed",
}


def normalize_exception(exc: BaseException) -> CanonicalError:
    if isinstance(exc, (TimeoutError, asyncio_timeout_types())):
        code = CanonicalErrorCode.TIMEOUT
    elif isinstance(exc, OSError):
        code = _ERRNO_CODES.get(exc.errno, CanonicalErrorCode.IO_ERROR)
    else:
        code = CanonicalErrorCode.UNKNOWN
    return CanonicalError(code, _MESSAGES[code], retryable=code is CanonicalErrorCode.TIMEOUT)


def asyncio_timeout_types() -> type:
    # asyncio.TimeoutError aliases TimeoutError on supported Pythons; this helper
    # keeps the taxonomy stdlib-only without importing event-loop machinery.
    return TimeoutError
