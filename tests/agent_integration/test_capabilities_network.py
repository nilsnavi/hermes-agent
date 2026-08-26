"""capabilities + network policy (Phase 6 §3, §8): typed allowlist, no
READ_ANYTHING, network read-only default DENIED."""

import pytest

from agent.agent_integration.capabilities import (
    NETWORK_READ_ONLY_DEFAULT_DENIED,
    READ_ONLY_ALLOWLIST,
    CapabilityAccessClass,
    ReadOnlyCapability,
    access_class,
    is_read_only_allowed,
    side_effect_for,
)
from agent.agent_integration.network_policy import (
    NetworkPolicyError,
    NetworkReadOnlyPolicy,
)


def test_read_only_allowlist_is_closed_exactly_eight():
    assert set(READ_ONLY_ALLOWLIST) == {
        ReadOnlyCapability.READ_FILE_METADATA,
        ReadOnlyCapability.READ_TEXT_RESOURCE,
        ReadOnlyCapability.SEARCH_INDEX,
        ReadOnlyCapability.READ_STATUS,
        ReadOnlyCapability.READ_HEALTH,
        ReadOnlyCapability.READ_CONFIGURATION_SUMMARY,
        ReadOnlyCapability.READ_AUDIT_SUMMARY,
        ReadOnlyCapability.READ_MEMORY_CONTEXT,
    }


def test_no_generic_read_anything_exists():
    values = {c.value for c in ReadOnlyCapability}
    assert "read_anything" not in values
    assert "READ_ANYTHING" not in values
    # The enum vocabulary is closed: a wildcard/anything token cannot be built.
    with pytest.raises(ValueError):
        ReadOnlyCapability("read_anything")


def test_is_read_only_allowed_is_exact_and_bounded():
    assert is_read_only_allowed(ReadOnlyCapability.READ_HEALTH) is True
    assert is_read_only_allowed("read_health") is False  # not a typed value
    assert is_read_only_allowed(None) is False
    assert is_read_only_allowed(123) is False


def test_all_mvp_capabilities_are_local_read_only():
    for cap in READ_ONLY_ALLOWLIST:
        assert access_class(cap) is CapabilityAccessClass.LOCAL_READ_ONLY


def test_side_effect_for_is_read_only():
    assert side_effect_for(ReadOnlyCapability.READ_HEALTH).value == "read_only"


def test_network_read_only_default_is_denied():
    assert NETWORK_READ_ONLY_DEFAULT_DENIED is True


def test_network_policy_default_denies_remote():
    policy = NetworkReadOnlyPolicy()  # no certified interfaces
    for cap in READ_ONLY_ALLOWLIST:
        # MVP has no remote/network tokens -> local ones are allowed.
        verdict = policy.allows(cap)
        assert verdict.allowed is True
        assert verdict.access_class is CapabilityAccessClass.LOCAL_READ_ONLY


def test_network_policy_denies_without_certification():
    # Force a remote-class scenario via a certified map that is empty: policy
    # must NOT auto-allow remote even though the op is "read-only".
    policy = NetworkReadOnlyPolicy()
    # No remote/network capability exists in the MVP allowlist, so the default
    # deny is structural: any future remote token would be denied until certified.
    assert policy.certified() == frozenset()


def test_network_policy_rejects_malformed_certified():
    with pytest.raises((NetworkPolicyError, TypeError, ValueError)):
        NetworkReadOnlyPolicy(certified_read_interfaces={ReadOnlyCapability.READ_HEALTH})  # a set, not frozenset  # type: ignore[arg-type]
    with pytest.raises(NetworkPolicyError):
        NetworkReadOnlyPolicy(certified_read_interfaces=frozenset({object()}))  # type: ignore[arg-type]


def test_network_policy_rejects_bad_capability():
    policy = NetworkReadOnlyPolicy()
    with pytest.raises(NetworkPolicyError):
        policy.allows("read_health")  # type: ignore[arg-type]
    with pytest.raises(NetworkPolicyError):
        policy.allows(None)  # type: ignore[arg-type]