"""Explicit lifecycle, recovery, and rollback contract tests."""
from dataclasses import dataclass
from copy import deepcopy

import pytest

from hermes_core.application.session_service import MutationStatus
from hermes_core.application.delivery_service import DeliveryApplicationStatus, DeliveryService
from hermes_core.domain.delivery import DeliveryResult, DeliveryState
from hermes_core.ports.delivery import DeliveryTransportError
from tests.hermes_core.test_session_persistence_hardening import make_service
from tests.hermes_core.test_delivery_recovery_contract import FakeTransport, make_delivery

from hermes_core.domain.migration import (
    ControllerState,
    DrainState,
    MigrationController,
    MigrationScope,
    Owner,
    Phase,
    ResultStatus,
    TransitionRequest,
)

SCOPE = MigrationScope(profile="p")


@dataclass(frozen=True)
class LifecycleObservation:
    step: str
    phase: Phase
    owner: Owner
    candidate_owner: Owner
    generation: int
    drain_state: DrainState
    status: ResultStatus


def request(transition_id, from_phase, to_phase, generation, owner=Owner.LEGACY, scope=SCOPE):
    return TransitionRequest(transition_id, generation, from_phase, to_phase, owner, scope, transition_id)


def run_full_rollback_rehearsal():
    controller = MigrationController(ControllerState(scope=SCOPE))
    trace = []

    def record(step, result):
        state = result.state
        trace.append(LifecycleObservation(step, state.phase, state.owner, state.candidate_owner, state.generation, state.drain_state, result.status))
        return result

    record("shadow", controller.apply(request("shadow", Phase.OFF, Phase.SHADOW, 0)))
    record("canary", controller.apply(request("canary", Phase.SHADOW, Phase.CANARY, 1)))
    record("draining", controller.apply(request("draining", Phase.CANARY, Phase.DRAINING, 2)))
    record("drain_requested", controller.drain("request", 3, SCOPE, DrainState.DRAIN_REQUESTED))
    record("drained", controller.drain("complete", 4, SCOPE, DrainState.DRAINED))
    record("cutover", controller.apply(request("cutover", Phase.DRAINING, Phase.CUTOVER, 5, Owner.HERMES_CORE)))
    record("rollback", controller.apply(request("rollback", Phase.CUTOVER, Phase.ROLLBACK, 6)))
    record("off", controller.apply(request("off", Phase.ROLLBACK, Phase.OFF, 7)))
    return trace


def test_lr1_initial_off_legacy():
    state = MigrationController(ControllerState(scope=SCOPE)).state
    assert state.phase is Phase.OFF
    assert state.owner is Owner.LEGACY
    assert state.generation == 0
    assert state.drain_state is DrainState.NOT_DRAINING


def test_lr2_off_to_shadow():
    result = MigrationController(ControllerState(scope=SCOPE)).apply(request("x", Phase.OFF, Phase.SHADOW, 0))
    assert result.status is ResultStatus.APPLIED
    assert result.state.phase is Phase.SHADOW
    assert result.state.owner is Owner.LEGACY


@pytest.mark.parametrize(("source", "target"), [(Phase.SHADOW, Phase.CANARY), (Phase.CANARY, Phase.DRAINING)])
def test_lr3_lr4_forward_phases(source, target):
    controller = MigrationController(ControllerState(phase=source, scope=SCOPE))
    result = controller.apply(request("forward", source, target, 0))
    assert result.status is ResultStatus.APPLIED
    assert result.state.phase is target
    assert result.state.owner is Owner.LEGACY


def test_lr5_lr6_drain_progression():
    controller = MigrationController(ControllerState(phase=Phase.DRAINING, scope=SCOPE))
    requested = controller.drain("request", 0, SCOPE, DrainState.DRAIN_REQUESTED)
    drained = controller.drain("complete", 1, SCOPE, DrainState.DRAINED)
    assert requested.status is ResultStatus.APPLIED
    assert requested.state.drain_state is DrainState.DRAIN_REQUESTED
    assert requested.state.generation == 1
    assert drained.status is ResultStatus.APPLIED
    assert drained.state.drain_state is DrainState.DRAINED
    assert drained.state.generation == 2


def test_lr7_cutover_before_drain_preserves_state():
    controller = MigrationController(ControllerState(phase=Phase.DRAINING, scope=SCOPE))
    before = controller.state
    result = controller.apply(request("cutover", Phase.DRAINING, Phase.CUTOVER, 0, Owner.HERMES_CORE))
    assert result.status is ResultStatus.DRAIN_REQUIRED
    assert controller.state == before


def test_lr8_lr9_cutover_transfers_authority():
    controller = MigrationController(ControllerState(phase=Phase.DRAINING, drain_state=DrainState.DRAINED, scope=SCOPE))
    result = controller.apply(request("cutover", Phase.DRAINING, Phase.CUTOVER, 0, Owner.HERMES_CORE))
    assert result.status is ResultStatus.APPLIED
    assert result.state.phase is Phase.CUTOVER
    assert result.state.owner is Owner.HERMES_CORE
    assert result.state.candidate_owner is Owner.LEGACY
    assert result.state.drain_state is DrainState.DRAINED
    assert result.state.generation == 1


def test_lr10_lr11_lr12_rollback_restores_legacy():
    controller = MigrationController(ControllerState(phase=Phase.CUTOVER, owner=Owner.HERMES_CORE, candidate_owner=Owner.LEGACY, drain_state=DrainState.DRAINED, scope=SCOPE))
    rollback = controller.apply(request("rollback", Phase.CUTOVER, Phase.ROLLBACK, 0))
    off = controller.apply(request("off", Phase.ROLLBACK, Phase.OFF, 1))
    assert rollback.status is ResultStatus.APPLIED
    assert rollback.state.phase is Phase.ROLLBACK
    assert rollback.state.owner is Owner.LEGACY
    assert rollback.state.candidate_owner is Owner.HERMES_CORE
    assert off.status is ResultStatus.APPLIED
    assert off.state.phase is Phase.OFF
    assert off.state.owner is Owner.LEGACY


def test_lr13_lr14_lr15_rejections_preserve_complete_state():
    controller = MigrationController(ControllerState(scope=SCOPE))
    before = controller.state
    assert controller.apply(request("stale", Phase.OFF, Phase.SHADOW, 9)).status is ResultStatus.CONFLICT
    assert controller.state == before
    wrong = request("scope", Phase.OFF, Phase.SHADOW, 0, scope=MigrationScope(profile="other"))
    assert controller.apply(wrong).status is ResultStatus.REJECTED
    assert controller.state == before
    illegal = request("illegal", Phase.OFF, Phase.CUTOVER, 0, Owner.HERMES_CORE)
    assert controller.apply(illegal).status is ResultStatus.INVALID_TRANSITION
    assert controller.state == before


def test_lr16_lr17_stale_and_wrong_scope_rollback():
    controller = MigrationController(ControllerState(phase=Phase.CUTOVER, owner=Owner.HERMES_CORE, candidate_owner=Owner.LEGACY, drain_state=DrainState.DRAINED, scope=SCOPE))
    before = controller.state
    assert controller.apply(request("stale", Phase.CUTOVER, Phase.ROLLBACK, 1)).status is ResultStatus.CONFLICT
    assert controller.state == before
    wrong = request("scope", Phase.CUTOVER, Phase.ROLLBACK, 0, scope=MigrationScope(profile="other"))
    assert controller.apply(wrong).status is ResultStatus.REJECTED
    assert controller.state == before


def test_lr18_failure_atomicity_for_drain_and_invalid_state():
    controller = MigrationController(ControllerState(phase=Phase.DRAINING, scope=SCOPE))
    before = controller.state
    assert controller.drain("jump", 0, SCOPE, DrainState.DRAINED).status is ResultStatus.REJECTED
    assert controller.state == before
    with pytest.raises(ValueError, match="drain_state_invalid"):
        controller.drain("bad", 0, SCOPE, "bad")
    assert controller.state == before


def test_lr19_kill_switch_blocks_and_unblocks_forward_progression():
    controller = MigrationController(ControllerState(scope=SCOPE))
    assert controller.set_kill_switch(True, 0).status is ResultStatus.APPLIED
    generation = controller.state.generation
    assert controller.set_kill_switch(True, generation).status is ResultStatus.NOOP
    blocked = controller.apply(request("forward", Phase.OFF, Phase.SHADOW, generation))
    assert blocked.status is ResultStatus.KILL_SWITCHED
    assert controller.state.generation == generation
    assert controller.set_kill_switch(False, generation).status is ResultStatus.APPLIED
    assert controller.apply(request("forward", Phase.OFF, Phase.SHADOW, generation + 1)).status is ResultStatus.APPLIED


def test_lr20_stale_kill_enable_and_disable_preserve_state():
    controller = MigrationController(ControllerState(scope=SCOPE))
    before = controller.state
    assert controller.set_kill_switch(True, 1).status is ResultStatus.CONFLICT
    assert controller.state == before
    assert controller.set_kill_switch(False, 1).status is ResultStatus.CONFLICT
    assert controller.state == before


def test_lr21_failover_is_fail_closed_and_audited():
    controller = MigrationController(ControllerState(scope=SCOPE))
    before = controller.state
    result = controller.failover("failover", 0, SCOPE)
    assert result.status is ResultStatus.FAILOVER_NOT_ALLOWED
    assert result.reason_code == "failover_unverified"
    assert result.audit.status is ResultStatus.FAILOVER_NOT_ALLOWED
    assert result.audit.previous_generation == result.audit.new_generation == 0
    assert controller.state == before


def test_lr22_session_recovery_is_real_failure_preservation():
    from tests.hermes_core.test_session_persistence_hardening import make_service
    session, repository, service = make_service()
    before = deepcopy(repository.stored)
    repository.fail = True
    result = service.acquire_result(session, "owner")
    assert result.status.value == "persistence_error"
    assert session.generation == before.generation
    assert repository.stored == before


def test_lr23_delivery_unknown_ack_is_real():
    from tests.hermes_core.test_delivery_recovery_contract import FakeTransport, make_delivery
    from hermes_core.application.delivery_service import DeliveryService
    from hermes_core.domain.delivery import DeliveryOutcome, DeliveryResult, DeliveryState
    delivery = make_delivery()
    result = DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(delivery)
    assert result.status.value == "unknown_ack"
    assert delivery.state is DeliveryState.UNKNOWN_ACK


def test_lr24_full_rehearsal_trace():
    trace = run_full_rollback_rehearsal()
    assert [item.step for item in trace] == ["shadow", "canary", "draining", "drain_requested", "drained", "cutover", "rollback", "off"]
    assert [item.phase for item in trace] == [Phase.SHADOW, Phase.CANARY, Phase.DRAINING, Phase.DRAINING, Phase.DRAINING, Phase.CUTOVER, Phase.ROLLBACK, Phase.OFF]
    assert [item.owner for item in trace[:5]] == [Owner.LEGACY] * 5
    assert trace[5].owner is Owner.HERMES_CORE
    assert trace[5].candidate_owner is Owner.LEGACY
    assert trace[5].drain_state is DrainState.DRAINED
    assert trace[6].owner is Owner.LEGACY
    assert trace[7].owner is Owner.LEGACY
    assert [item.status for item in trace] == [ResultStatus.APPLIED] * 8
    assert [item.generation for item in trace] == list(range(1, 9))


def test_audit_events_cover_applied_conflict_rejected_kill_and_failover():
    controller = MigrationController(ControllerState(scope=SCOPE))
    applied = controller.apply(request("applied", Phase.OFF, Phase.SHADOW, 0))
    conflict = controller.apply(request("conflict", Phase.SHADOW, Phase.CANARY, 0))
    rejected = controller.apply(request("rejected", Phase.SHADOW, Phase.CANARY, 1, scope=MigrationScope(profile="other")))
    controller.set_kill_switch(True, 1)
    killed = controller.apply(request("killed", Phase.SHADOW, Phase.CANARY, 2))
    failover = controller.failover("failover", 2, SCOPE)
    assert applied.audit.status is ResultStatus.APPLIED
    assert conflict.audit.status is ResultStatus.CONFLICT
    assert rejected.audit.status is ResultStatus.REJECTED
    assert killed.audit.status is ResultStatus.KILL_SWITCHED
    assert failover.audit.status is ResultStatus.FAILOVER_NOT_ALLOWED
    for event in (applied.audit, conflict.audit, rejected.audit, killed.audit, failover.audit):
        assert event.transition_id
        assert event.previous_generation <= event.new_generation


def test_sr1_acquire_persistence_failure():
    session, repository, service = make_service()
    source_before, durable_before = deepcopy(session), deepcopy(repository.stored)
    repository.fail = True
    result = service.acquire_result(session, "a")
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session == source_before
    assert repository.stored == durable_before


def test_sr2_stale_cas_conflict():
    session, repository, service = make_service()
    stale = service.resume(session.session_id)
    source_before = deepcopy(stale)
    assert service.acquire_result(session, "a").committed
    durable_before = deepcopy(repository.stored)
    result = service.acquire_result(stale, "b")
    assert result.status is MutationStatus.CONFLICT
    assert stale == source_before
    assert session == durable_before
    assert repository.stored == durable_before


def test_sr3_release_persistence_failure():
    session, repository, service = make_service()
    assert service.acquire_result(session, "a").committed
    source_before, durable_before = deepcopy(session), deepcopy(repository.stored)
    repository.fail = True
    result = service.release_result(session, "a", session.lease_generation)
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session == source_before
    assert repository.stored == durable_before


def test_sr4_close_persistence_failure():
    session, repository, service = make_service()
    assert service.acquire_result(session, "a").committed
    source_before, durable_before = deepcopy(session), deepcopy(repository.stored)
    repository.fail = True
    result = service.close_result(session, "a", session.lease_generation)
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session == source_before
    assert repository.stored == durable_before


def test_sr5_stale_owner_rejected():
    session, repository, service = make_service()
    assert service.acquire_result(session, "a").committed
    stale_generation = session.lease_generation
    assert service.release_result(session, "a", stale_generation).committed
    assert service.acquire_result(session, "b").committed
    source_before, durable_before = deepcopy(session), deepcopy(repository.stored)
    for operation in (service.release_result, service.close_result):
        result = operation(session, "a", stale_generation)
        assert result.status is MutationStatus.REJECTED
        assert session == source_before
        assert repository.stored == durable_before


def test_dr1_confirmed_success():
    delivery = make_delivery()
    transport = FakeTransport(DeliveryResult(True, external_id="ack"))
    result = DeliveryService(transport).deliver_result(delivery)
    assert result.status is DeliveryApplicationStatus.SUCCESS
    assert result.state is delivery.state is DeliveryState.DELIVERED
    assert result.external_id == "ack"
    assert transport.calls == delivery.attempts == 1


def test_dr2_confirmed_failure():
    delivery = make_delivery()
    transport = FakeTransport(DeliveryResult(False, error="rejected", error_code="denied"))
    result = DeliveryService(transport).deliver_result(delivery)
    assert result.status is DeliveryApplicationStatus.FAILURE
    assert result.state is delivery.state is DeliveryState.FAILED
    assert (result.error, result.error_code) == ("rejected", "denied")
    assert transport.calls == delivery.attempts == 1


class RaisingTransport(FakeTransport):
    def send(self, delivery):
        self.calls += 1
        raise self.result


def test_dr3_transport_error_unknown_ack():
    delivery = make_delivery()
    transport = RaisingTransport(DeliveryTransportError("ack lost", external_id="possible-ack"))
    result = DeliveryService(transport).deliver_result(delivery)
    assert result.status is DeliveryApplicationStatus.TRANSPORT_ERROR
    assert result.state is delivery.state is DeliveryState.UNKNOWN_ACK
    assert (result.error, result.error_code) == ("ack lost", "ambiguous_transport")
    assert result.external_id == "possible-ack"
    assert not result.retryable
    assert transport.calls == delivery.attempts == 1


@pytest.mark.parametrize(("operation", "status", "state"), [
    (DeliveryService.reconcile_delivered, DeliveryApplicationStatus.SUCCESS, DeliveryState.DELIVERED),
    (DeliveryService.reconcile_failed, DeliveryApplicationStatus.FAILURE, DeliveryState.FAILED),
])
def test_dr4_explicit_reconciliation(operation, status, state):
    delivery = make_delivery()
    transport = RaisingTransport(DeliveryTransportError("ack lost"))
    initial = DeliveryService(transport).deliver_result(delivery)
    assert initial.state is delivery.state is DeliveryState.UNKNOWN_ACK
    result = operation(delivery)
    assert result.status is status
    assert result.state is delivery.state is state
    assert transport.calls == delivery.attempts == 1


def test_dr5_explicit_abandonment():
    delivery = make_delivery()
    transport = RaisingTransport(DeliveryTransportError("ack lost"))
    initial = DeliveryService(transport).deliver_result(delivery)
    assert initial.state is delivery.state is DeliveryState.UNKNOWN_ACK
    result = DeliveryService.abandon(delivery)
    assert result.status is DeliveryApplicationStatus.ABANDONED
    assert result.state is delivery.state is DeliveryState.ABANDONED
    assert transport.calls == delivery.attempts == 1


def test_dr6_runtime_error_propagates():
    delivery = make_delivery()
    error = RuntimeError("bug")
    transport = RaisingTransport(error)
    with pytest.raises(RuntimeError, match="bug") as raised:
        DeliveryService(transport).deliver_result(delivery)
    assert raised.value is error
    assert delivery.state is DeliveryState.ATTEMPTING
    assert transport.calls == delivery.attempts == 1
