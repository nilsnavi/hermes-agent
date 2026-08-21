"""Test unknown outcome: no blind start, no retry, manual review."""
from agent.service_restart_canary.unknown_outcome import classify_outcome, OutcomeClass, UnknownOutcomePolicy


def test_stop_unknown_no_blind_start():
    assert classify_outcome("STOP_UNKNOWN") == OutcomeClass.DO_NOT_BLIND_START


def test_start_unknown_no_restart():
    assert classify_outcome("START_UNKNOWN") == OutcomeClass.DO_NOT_RESTART


def test_timeout_manual_review():
    assert classify_outcome("COMMAND_TIMEOUT") == OutcomeClass.MANUAL_REVIEW


def test_connection_interrupted_manual():
    assert classify_outcome("CONNECTION_INTERRUPTED") == OutcomeClass.MANUAL_REVIEW


def test_old_pid_survives_halt():
    assert classify_outcome("OLD_PID_SURVIVES") == OutcomeClass.HALT_STOP


def test_auto_retry_false():
    p = UnknownOutcomePolicy()
    assert p.AUTO_RETRY is False