from __future__ import annotations
import errno, pytest
from agent.sandbox_runtime.errors import CanonicalErrorCode, normalize_exception


@pytest.mark.parametrize("exc,code", [(OSError(errno.ENOSPC,"full"),CanonicalErrorCode.NO_SPACE),(PermissionError(errno.EACCES,"denied"),CanonicalErrorCode.PERMISSION_DENIED),(OSError(errno.EROFS,"ro"),CanonicalErrorCode.READ_ONLY_FILESYSTEM),(TimeoutError(),CanonicalErrorCode.TIMEOUT)])
def test_failures_normalize_without_raw_exception(exc,code):
    out=normalize_exception(exc)
    assert out.code is code
    assert type(exc).__name__ not in out.message


@pytest.mark.parametrize("case", ["snapshot_missing","original_locked","permissions_restore","disk_full","destination_disappears","parent_changes","symlink_introduced","service_refuses","process_dies","rollback_verify"])
def test_rollback_failure_matrix_preserves_both_errors(case):
    from agent.sandbox_runtime.rollback import rollback_failure_disposition
    out=rollback_failure_disposition("original-failure",case)
    assert out.disposition=="MANUAL_REVIEW_REQUIRED"
    assert out.original_error=="original-failure"
    assert out.rollback_error==case
