from hermes_core.application.delivery_service import DeliveryApplicationStatus, DeliveryService
from hermes_core.domain.delivery import Delivery, DeliveryOutcome, DeliveryResult, DeliveryState


class FakeTransport:
    def __init__(self, result): self.result, self.calls = result, 0
    def send(self, delivery): self.calls += 1; return self.result
    def edit(self, delivery): return self.result


def make_delivery(): return Delivery("o", "k", "payload")


def test_d1_pending(): assert make_delivery().state is DeliveryState.PENDING
def test_d2_attempting():
    d = make_delivery(); d.begin_attempt(); assert d.state is DeliveryState.ATTEMPTING
def test_d3_confirmed_success():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(True, "id"))).deliver_result(d)
    assert r.status is DeliveryApplicationStatus.SUCCESS and d.state is DeliveryState.DELIVERED
def test_d4_confirmed_failure():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(False, error="bad"))).deliver_result(d)
    assert r.status is DeliveryApplicationStatus.FAILURE and d.state is DeliveryState.FAILED
def test_d5_ambiguous_ack():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(d)
    assert r.status is DeliveryApplicationStatus.UNKNOWN_ACK and d.state is DeliveryState.UNKNOWN_ACK
def test_d6_unknown_is_not_failed():
    d = make_delivery(); d.begin_attempt(); d.mark_unknown(); assert d.state is not DeliveryState.FAILED
def test_d7_unknown_does_not_retry():
    t = FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK)); d = make_delivery(); DeliveryService(t).deliver_result(d)
    assert t.calls == 1 and d.attempts == 1
def test_d8_external_id_preserved():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(True, "ext"))).deliver_result(d); assert r.external_id == "ext"
def test_d9_retryable_preserved():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(False, retryable=True))).deliver_result(d); assert r.retryable
def test_d10_error_classification_preserved():
    d = make_delivery(); r = DeliveryService(FakeTransport(DeliveryResult(False, error="timeout", error_code="E_TIMEOUT"))).deliver_result(d); assert (r.error, r.error_code) == ("timeout", "E_TIMEOUT")
def test_d11_unknown_reconcile_delivered():
    d = make_delivery(); DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(d); assert DeliveryService.reconcile_delivered(d).status is DeliveryApplicationStatus.SUCCESS
def test_d12_unknown_reconcile_failed():
    d = make_delivery(); DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(d); assert DeliveryService.reconcile_failed(d).status is DeliveryApplicationStatus.FAILURE
def test_d13_unknown_abandon():
    d = make_delivery(); DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(d); result = DeliveryService.abandon(d); assert d.state is DeliveryState.ABANDONED and result.status is DeliveryApplicationStatus.ABANDONED
def test_d14_abandoned_terminal():
    d = make_delivery(); d.begin_attempt(); d.mark_unknown(); d.abandon(); assert DeliveryService.reconcile_delivered(d).status is DeliveryApplicationStatus.REJECTED; assert DeliveryService.reconcile_failed(d).status is DeliveryApplicationStatus.REJECTED; assert DeliveryService.abandon(d).status is DeliveryApplicationStatus.REJECTED
def test_d15_delivered_cannot_be_rewritten():
    d = make_delivery(); d.begin_attempt(); d.mark_delivered()
    try: d.mark_failed(); assert False
    except ValueError: pass
def test_d16_application_distinguishes_failure_and_unknown():
    d1, d2 = make_delivery(), make_delivery(); s = DeliveryService(FakeTransport(DeliveryResult(False)))
    a = s.deliver_result(d1); b = DeliveryService(FakeTransport(DeliveryResult(False, outcome=DeliveryOutcome.UNKNOWN_ACK))).deliver_result(d2)
    assert a.status is DeliveryApplicationStatus.FAILURE and b.status is DeliveryApplicationStatus.UNKNOWN_ACK
def test_d17_provider_exception_does_not_enter_contract():
    from hermes_core.ports.delivery import DeliveryTransportError
    class ProviderSDKError(Exception): pass
    class ProviderAdapter:
        def __init__(self): self.calls = 0
        def send(self, delivery):
            self.calls += 1
            try:
                raise ProviderSDKError("secret sdk object")
            except ProviderSDKError as error:
                raise DeliveryTransportError("provider timeout", retryable=True) from error
        def edit(self, delivery): raise AssertionError("not used")

    d = make_delivery()
    adapter = ProviderAdapter()
    result = DeliveryService(adapter).deliver_result(d)
    assert adapter.calls == 1
    assert d.state is DeliveryState.UNKNOWN_ACK
    assert result.status is DeliveryApplicationStatus.TRANSPORT_ERROR
    assert result.error == "provider timeout"
    assert result.error_code == "ambiguous_transport"
    assert "secret sdk object" not in str(result)
    assert adapter.calls == 1  # no automatic retry


def test_delivery_result_rejects_contradictory_outcome_flags():
    import pytest
    with pytest.raises(ValueError): DeliveryResult(True, outcome=DeliveryOutcome.CONFIRMED_FAILURE)
    with pytest.raises(ValueError): DeliveryResult(False, outcome=DeliveryOutcome.CONFIRMED_SUCCESS)
def test_d18_existing_contract_remains_valid():
    d = make_delivery(); d.begin_attempt(); d.mark_failed(); assert d.state is DeliveryState.FAILED


def test_unclassified_programmer_exception_propagates_and_requires_recovery_inspection():
    class BuggyTransport(FakeTransport):
        def send(self, delivery):
            self.calls += 1
            raise RuntimeError("programmer bug")

    transport = BuggyTransport(DeliveryResult(True))
    delivery = make_delivery()
    import pytest
    with pytest.raises(RuntimeError, match="programmer bug"):
        DeliveryService(transport).deliver_result(delivery)
    assert delivery.state is DeliveryState.ATTEMPTING
    assert delivery.state is not DeliveryState.FAILED
    assert delivery.state is not DeliveryState.UNKNOWN_ACK
    assert transport.calls == 1  # no automatic retry; recovery inspection is required
