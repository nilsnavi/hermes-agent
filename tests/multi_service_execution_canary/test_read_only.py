import json

from agent.multi_service_execution_canary import CanaryDecision, CanaryServiceRegistry, build_canary_pipeline, build_service_set


def test_registry_and_service_set_inspection_create_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    registry = CanaryServiceRegistry()
    service_set = build_service_set(registry.service_ids(), registry, now=1.0)
    assert service_set.registry_digest == registry.digest
    assert set(tmp_path.rglob("*")) == before


def test_denied_real_execute_does_not_mutate_store_after_construction(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    store_path = tmp_path / "canary-store.json"
    before = store_path.read_bytes()
    assert pipeline.real_execute(exact_request(), **green_gates) is CanaryDecision.DENIED
    assert store_path.read_bytes() == before
    assert json.loads(before)["receipts"] == {}


def test_pre_admission_denial_leaves_no_claim_or_receipt(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    pipeline.evaluate(exact_request(), **(green_gates | {"identity_valid": False}))
    state = json.loads((tmp_path / "canary-store.json").read_text())
    assert state["claims"] == {}
    assert state["receipts"] == {}
    assert state["budget_attempts"] == state["budget_success"] == 0
