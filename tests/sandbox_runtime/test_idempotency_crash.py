from __future__ import annotations
import pytest
from agent.sandbox_runtime.recovery import disposition_for_state, RecoveryDisposition


@pytest.mark.parametrize("state,expected", [("PLANNED",RecoveryDisposition.SAFE_TO_ROLLBACK),("PREFLIGHT_OK",RecoveryDisposition.SAFE_TO_ROLLBACK),("APPROVED",RecoveryDisposition.SAFE_TO_ROLLBACK),("SNAPSHOT_CREATED",RecoveryDisposition.SAFE_TO_ROLLBACK),("EXECUTING",RecoveryDisposition.MANUAL_REVIEW_REQUIRED),("EXECUTED",RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),("VERIFYING",RecoveryDisposition.MANUAL_REVIEW_REQUIRED),("VERIFIED",RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),("HEALTH_CHECKING",RecoveryDisposition.MANUAL_REVIEW_REQUIRED),("COMMITTED",RecoveryDisposition.TERMINAL),("ROLLING_BACK",RecoveryDisposition.MANUAL_REVIEW_REQUIRED),("ROLLED_BACK",RecoveryDisposition.TERMINAL)])
def test_idempotency_crash_matrix_never_reexecutes(state,expected):
    out=disposition_for_state(state, execution_started=state in {"EXECUTING","EXECUTED","VERIFYING","VERIFIED","HEALTH_CHECKING","COMMITTED","ROLLING_BACK","ROLLED_BACK"}, execution_completed=state not in {"EXECUTING"})
    assert out is expected
    if state=="EXECUTING": assert out is RecoveryDisposition.MANUAL_REVIEW_REQUIRED
