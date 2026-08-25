import dataclasses

import pytest

from agent.multi_service_execution_canary import BASELINE_SHA, OPERATION, build_service_set


def test_exact_two_fixture_set_is_normalized_and_bound(exact_registry):
    value = build_service_set(reversed(exact_registry.service_ids()), exact_registry, now=20.0, ttl=30.0)
    assert value.service_ids == ("canary-service-a", "canary-service-b")
    assert tuple(p.service_id for p in value.service_profiles) == value.service_ids
    assert value.registry_digest == exact_registry.digest
    assert value.graph_digest == exact_registry.graph_digest
    assert value.baseline_sha == BASELINE_SHA
    assert value.operation == OPERATION
    assert value.expires_monotonic == 50.0


@pytest.mark.parametrize("service_ids", [(), ("canary-service-a",), ("canary-service-a", "canary-service-b", "extra"), ("gateway", "canary-service-b"), ("canary-service-a", "canary-service-a")])
def test_any_non_exact_service_set_is_rejected(exact_registry, service_ids):
    with pytest.raises(ValueError, match="exact two-service"):
        build_service_set(service_ids, exact_registry)


def test_semantic_hash_binds_generation_and_is_order_independent(exact_registry):
    ab = build_service_set(exact_registry.service_ids(), exact_registry, generation=1)
    ba = build_service_set(tuple(reversed(exact_registry.service_ids())), exact_registry, generation=1)
    next_generation = dataclasses.replace(ab, generation=2)
    assert ab.semantic_hash() == ba.semantic_hash()
    assert ab.semantic_hash() != next_generation.semantic_hash()


def test_registry_profiles_are_frozen_exact_non_systemd_fixtures(exact_registry):
    profiles = exact_registry.profiles()
    assert len(profiles) == 2
    assert {p.fixture_kind for p in profiles} == {"NON_SYSTEMD_EXECUTION_FIXTURE"}
    assert {p.service_class for p in profiles} == {"HERMES_AUXILIARY"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        profiles[0].identity = "forged"
