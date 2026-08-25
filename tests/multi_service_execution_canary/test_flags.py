from agent.multi_service_execution_canary import (
    ALLOWED_MODES, ENABLED, MODE, REAL_CHILD_EXECUTION_ENABLED,
    enabled, mode, real_execution_permitted, simulation_permitted,
)


def test_flags_default_to_fail_closed():
    assert enabled({}) is False
    assert mode({}) == "off"
    assert simulation_permitted({}) is False
    assert real_execution_permitted({}) is False


def test_enable_values_are_explicit_and_case_insensitive():
    for value in ("1", "true", "TRUE", " yes "):
        assert enabled({ENABLED: value}) is True
    for value in ("", "0", "on", "enabled", "false"):
        assert enabled({ENABLED: value}) is False


def test_unknown_mode_falls_back_to_off():
    assert ALLOWED_MODES == ("off", "shadow", "canary")
    assert mode({MODE: "production"}) == "off"
    assert mode({MODE: " CANARY "}) == "canary"


def test_only_enabled_shadow_or_canary_permits_simulation():
    for candidate in ALLOWED_MODES:
        expected = candidate in {"shadow", "canary"}
        assert simulation_permitted({ENABLED: "true", MODE: candidate}) is expected
    assert REAL_CHILD_EXECUTION_ENABLED is False
    assert real_execution_permitted({ENABLED: "true", MODE: "canary"}) is False
