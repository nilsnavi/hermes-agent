"""Sprint 1.3.17 — sealed execution authority (TDD RED candidates)."""

from __future__ import annotations

import copy
import pickle

import pytest

from agent.multi_service_execution.authority import (
    AuthorityDenied, ExecutionRuntime, MultiServiceExecutionAuthority,
)
from agent.multi_service_execution.exceptions import MultiServiceExecutionError
from agent.multi_service_execution.executor import BoundedMultiServiceExecutor
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from tests.multi_service_execution.conftest import make_coord_plan, make_exec_plan


def _auth(runtime, plan, now=1000.0):
    return runtime._issue(plan, now_monotonic=now, ttl_s=1000.0)


def test_external_authority_mint_rejected():
    # A caller cannot fabricate a valid authority: any object not issued by a
    # runtime is DENIED (hand-minted / forged token / wrong owner).
    from agent.multi_service_execution.authority import _AuthorityPayload
    from agent.multi_service_execution.models import ExecutionMode
    cp = make_coord_plan(("svc-a",))
    plan = make_exec_plan(cp)
    runtime = ExecutionRuntime()
    forged_payload = _AuthorityPayload(
        global_tx_id=plan.global_tx_id, plan_hash=plan.plan_hash(),
        generation=plan.generation, service_set=frozenset(plan.service_set),
        prepared_token_set=frozenset(), approval_set=frozenset(),
        budget_reservations=frozenset(), lock_owner_set=frozenset(),
        baseline_sha=plan.baseline_sha, graph_digest=plan.graph_digest,
        registry_digest=plan.registry_digest, ttl_until_monotonic=99999.0,
        clock_provenance="monotonic", execution_mode=ExecutionMode.REHEARSAL,
    )
    forged = MultiServiceExecutionAuthority(
        _instance_token=b"attacker-token", _owner_instance_id=runtime.instance_id,
        _payload=forged_payload, _authority_id="forged",
    )
    with pytest.raises(AuthorityDenied):
        runtime._verify_and_consume(runtime, forged, 1000.0)
    # and the raw executor path yields 0 adapter calls for an un-issued authority
    executor = BoundedMultiServiceExecutor()
    adapter = FakeServiceAdapter()
    res = executor.execute(runtime, forged, plan, adapter, now_monotonic=1000.0)
    assert res.adapter_call_count == 0
    assert res.global_state.value.startswith("EXECUTION_DENIED")


def test_authority_binds_to_exact_plan():
    runtime = ExecutionRuntime()
    p1 = make_exec_plan(make_coord_plan(("svc-a",), tx_id="t1"))
    a = _auth(runtime, p1)
    assert a.binds(p1) is True
    p2 = make_exec_plan(make_coord_plan(("svc-a",), tx_id="t2"))
    assert a.binds(p2) is False  # different tx -> different plan hash


def test_authority_wrong_runtime_denied():
    r1, r2 = ExecutionRuntime(), ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = _auth(r1, plan)
    with pytest.raises(AuthorityDenied):
        r2._verify_and_consume(r2, auth, 1000.0)


def test_authority_deepcopy_denied():
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = _auth(runtime, plan)
    dup = copy.deepcopy(auth)
    with pytest.raises(AuthorityDenied):
        runtime._verify_and_consume(runtime, dup, 1000.0)


def test_authority_pickle_denied():
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = _auth(runtime, plan)
    restored = pickle.loads(pickle.dumps(auth))
    with pytest.raises(AuthorityDenied):
        runtime._verify_and_consume(runtime, restored, 1000.0)


def test_authority_one_shot_consume():
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = _auth(runtime, plan)
    runtime._verify_and_consume(runtime, auth, 1000.0)  # consumes
    with pytest.raises(AuthorityDenied):
        runtime._verify_and_consume(runtime, auth, 1000.0)  # already used


def test_authority_ttl_expiry_denied():
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = runtime._issue(plan, now_monotonic=0.0, ttl_s=10.0)
    with pytest.raises(AuthorityDenied):
        runtime._verify_and_consume(runtime, auth, 9999.0)  # expired


def test_no_public_authority_factory_in_package():
    import agent.multi_service_execution as m
    # mint helpers are private; no public mint function is exported
    assert not any("mint" in n.lower() for n in m.__all__)
    assert "BoundedMultiServiceExecutor" not in m.__all__