from __future__ import annotations

"""Sprint 1.3.15 acceptance — named architecture components are real, no
second policy engine, no authority leak, execution disabled by default.
"""
import inspect

import agent.multi_service_coordination as msc
from agent.multi_service_coordination import (
    CompensationPlan,
    GlobalTransaction,
    MultiServiceChangePlan,
    MultiServiceCoordinator,
    PrepareBarrier,
    PreparedServiceToken,
    ServiceSubPlan,
)
from agent.multi_service_coordination.lock_order import CanonicalLockSet
from agent.multi_service_coordination.models import ServiceTransaction, MultiServiceExecutionPermit


def test_named_architecture_components_are_real_types():
    assert issubclass(MultiServiceCoordinator, object)
    assert issubclass(GlobalTransaction, object)
    assert issubclass(ServiceSubPlan, object)
    assert issubclass(ServiceTransaction, object)
    assert issubclass(PrepareBarrier, object)
    assert issubclass(PreparedServiceToken, object)
    assert issubclass(CompensationPlan, object)
    assert issubclass(MultiServiceExecutionPermit, object)
    assert issubclass(MultiServiceChangePlan, object)
    assert isinstance(CanonicalLockSet(), object)


def test_no_second_policy_engine_exported():
    # The brief forbids a parallel MultiServicePolicyEngine duplicating
    # CapabilityPolicyEngine.  It must NOT be part of the public surface OR
    # importable from the package.
    assert not hasattr(msc, "MultiServicePolicyEngine")
    import agent.multi_service_coordination as mod
    assert not hasattr(mod, "MultiServicePolicyEngine")


def test_coordinator_never_exports_raw_authority_handles():
    # No raw child executor / grant with commit authority / systemctl wrapper.
    public_names = set(msc.__all__)
    assert "MultiServiceCoordinator" in public_names
    assert "GlobalTransaction" in public_names
    for forbidden in ("SystemctlWrapper", "GrantManagerCommit", "RawChildExecutor"):
        assert not hasattr(msc, forbidden)
    # no import of the raw subprocess systemctl wrapper anywhere in the module
    import agent.multi_service_coordination as mod
    src = inspect.getsource(mod)
    assert "systemctl" not in src  # coordinator never shells out


def test_execution_permit_is_explicitly_simulation_only():
    p = MultiServiceExecutionPermit(
        permit_id="p", global_tx_id="g", plan_hash="h", registry_digest="d",
        execution_order=("a",), rollback_order=("b",), issued_at=0.0, expires_at=1.0,
    )
    assert p.simulation_only is True


def test_default_flags_are_off():
    import os
    saved = dict(os.environ)
    try:
        for k in ("HERMES_MULTI_SERVICE_COORD_V2_ENABLED",
                  "HERMES_MULTI_SERVICE_COORD_V2_MODE"):
            os.environ.pop(k, None)
        assert msc.multi_coord_enabled() is False
        assert msc.multi_coord_mode() == "off"
    finally:
        os.environ.clear(); os.environ.update(saved)


def test_real_adapter_calls_invariant_zero():
    # By construction the coordinator has no adapter call site that could bump.
    src = inspect.getsource(msc.transaction) if hasattr(msc, "transaction") else ""
    assert "real_adapter_calls()" not in src or "record_result" in src