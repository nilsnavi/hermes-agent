"""Feature flag parsing tests (Sprint 1.0.6 §5-6)."""

from agent.gateway_v2.flags import FeatureFlags, FLAG_NAMES, parse_flag


def test_all_flags_default_false():
    flags = FeatureFlags()
    assert flags.to_dict() == {
        "enabled": False, "persistence": False, "orchestrator": False,
        "shadow": False, "canary": False,
    }
    assert flags.mode() == "legacy"


def test_absent_env_all_false():
    flags = FeatureFlags.from_env({})
    assert flags.mode() == "legacy"
    assert not any(flags.to_dict().values())


def test_strict_parser():
    assert parse_flag("true") is True
    assert parse_flag("TRUE") is True
    assert parse_flag("1") is True
    assert parse_flag("yes") is True
    assert parse_flag("false") is False
    assert parse_flag("0") is False  # "0" must NEVER be truthy
    assert parse_flag("no") is False
    assert parse_flag("banana") is False  # garbage → fail closed
    assert parse_flag("") is False
    assert parse_flag(None) is False


def test_flag_names_complete():
    assert set(FLAG_NAMES) == {
        "HERMES_RUNTIME_V2_ENABLED",
        "HERMES_RUNTIME_V2_PERSISTENCE",
        "HERMES_RUNTIME_V2_ORCHESTRATOR",
        "HERMES_RUNTIME_V2_SHADOW",
        "HERMES_RUNTIME_V2_CANARY",
    }


def test_mode_matrix():
    assert FeatureFlags().mode() == "legacy"
    assert FeatureFlags(shadow=True).mode() == "legacy"  # enabled gates all
    assert FeatureFlags(enabled=True).mode() == "legacy"
    assert FeatureFlags(enabled=True, shadow=True).mode() == "shadow"
    assert FeatureFlags(enabled=True, canary=True).mode() == "canary"
    # canary wins over shadow
    assert FeatureFlags(enabled=True, shadow=True, canary=True).mode() == "canary"


def test_environment_roundtrip():
    env = {
        "HERMES_RUNTIME_V2_ENABLED": "true",
        "HERMES_RUNTIME_V2_PERSISTENCE": "1",
        "HERMES_RUNTIME_V2_ORCHESTRATOR": "0",
        "HERMES_RUNTIME_V2_SHADOW": "no",
        "HERMES_RUNTIME_V2_CANARY": "false",
    }
    flags = FeatureFlags.from_env(env)
    assert flags.enabled is True
    assert flags.persistence is True
    assert flags.orchestrator is False
    assert flags.shadow is False
    assert flags.canary is False


def test_invalid_flag_value_fails_closed():
    env = {"HERMES_RUNTIME_V2_ENABLED": "maybe", "HERMES_RUNTIME_V2_CANARY": "yes"}
    flags = FeatureFlags.from_env(env)
    assert flags.enabled is False
    assert flags.canary is True
    assert flags.mode() == "legacy"  # master gate off → everything off
