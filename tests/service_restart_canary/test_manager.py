"""Test manager (live contract): orchestration with fake adapter, exactly-once,
kill-switch, replay -> DUPLICATE adapter=0."""
import tempfile, time
from agent.service_restart_canary.manager import RestartCanaryManager
from agent.service_restart_canary.allowlist import default_allowlist, CANARY_SERVICE_ID, CANARY_UNIT
from agent.service_restart_canary.approval import ApprovalManager
from agent.service_restart_canary.budget import RestartBudget
from agent.service_restart_canary.breaker import RestartCircuitBreaker
from agent.service_restart_canary.idempotency import DurableIdempotencyStore
from agent.service_restart_canary.lock import DurableServiceLock
from agent.service_restart_canary.executor import RestartExecutor, FakeRestartAdapter
from agent.service_restart_canary.models import RestartApproval, RestartOutcome
from agent.service_restart_canary.flags import canary_active


def _approval(approvals, aid="a1"):
    a = RestartApproval(
        approval_id=aid, service_id=CANARY_SERVICE_ID, profile_version=1,
        operation="RESTART", old_pid_identity="pid/100/si", old_start_identity="si",
        graph_digest="gd", ports=(9000,), config_hash="ch", pre_health="HEALTHY",
        risk="HIGH", blast_radius="SERVICE", quiescence_contract="q",
        startup_contract="s", rollback_plan="r", baseline_sha="sha",
        ttl=300.0, created_at=time.time(),
    )
    return approvals.create(a)


def _manager(tmp, *, kill_switch=False, approvals=None):
    approvals = approvals or ApprovalManager()
    budget = RestartBudget()
    breaker = RestartCircuitBreaker()
    idem = DurableIdempotencyStore(tmp + "/idem")
    lock = DurableServiceLock(tmp + "/locks")
    ex = RestartExecutor(default_allowlist(), adapter=FakeRestartAdapter(),
                         store_dir=tmp + "/exec", kill_switch=kill_switch)
    return RestartCanaryManager(
        default_allowlist(), approvals=approvals, budget=budget, breaker=breaker,
        idem=idem, lock=lock, executor=ex, store_dir=tmp,
        allow_real=False, kill_switch=kill_switch, owner_pid=100, owner_start="si-owner")


def _args(**kw):
    d = dict(service_id=CANARY_SERVICE_ID, unit_identity=CANARY_UNIT,
             transaction_intent="intent-1", old_pid_identity="pid/100/si",
             old_start_identity="si", profile_version=1, config_hash="ch",
             graph_digest="gd", approval_id="a1", pre_health="HEALTHY")
    d.update(kw)
    return d


def test_kill_switch_blocks():
    tmp = tempfile.mkdtemp()
    m = _manager(tmp, kill_switch=True)
    out, calls = m.run(**_args())
    assert out == RestartOutcome.CANARY_DISABLED
    assert calls == 0


def test_unregistered():
    tmp = tempfile.mkdtemp()
    approvals = ApprovalManager(); _approval(approvals)
    m = _manager(tmp, approvals=approvals)
    from agent.service_restart_canary.exceptions import NotRegistered
    import pytest
    with pytest.raises(NotRegistered):
        m.run(**{**_args(), "service_id": "ghost", "unit_identity": "ghost.service"})


def test_approval_missing():
    tmp = tempfile.mkdtemp()
    m = _manager(tmp)
    from agent.service_restart_canary.exceptions import ApprovalMissing
    import pytest
    with pytest.raises(ApprovalMissing):
        m.run(**_args())


def test_lucky_commit():
    tmp = tempfile.mkdtemp()
    approvals = ApprovalManager(); _approval(approvals)
    m = _manager(tmp, approvals=approvals)
    out, calls = m.run(**_args())
    assert out == RestartOutcome.COMMITTED
    # fake adapter call recorded in executor counter
    assert calls == 1  # durable adapter counter bumped


def test_replay_duplicate():
    tmp = tempfile.mkdtemp()
    b = RestartBudget()
    # budget exhausted -> second attempt denied even before idempotency replay, but
    # replay check runs first -> DUPLICATE with adapter=0 either way.
    approvals = ApprovalManager(); _approval(approvals)
    m = _manager(tmp, approvals=approvals)
    m.run(**_args())
    out, calls = m.run(**_args())
    assert out == RestartOutcome.DUPLICATE
    assert calls == 1  # no SECOND adapter call


def test_budget_exhausted_after_success():
    tmp = tempfile.mkdtemp()
    approvals = ApprovalManager()
    _approval(approvals, "a1")
    _approval(approvals, "a2")
    m = _manager(tmp, approvals=approvals)
    m.run(**_args())  # success consumes attempt 1 = budget successes 1
    # second distinct intent: idempotency key differs -> not duplicate, budget exhausted
    from agent.service_restart_canary.exceptions import BudgetExceeded
    import pytest
    with pytest.raises(BudgetExceeded):
        m.run(**_args(transaction_intent="intent-2", approval_id="a2"))


def test_flag_required_for_live():
    assert canary_active({}) is False