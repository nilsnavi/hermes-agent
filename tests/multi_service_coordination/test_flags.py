from __future__ import annotations

from agent.multi_service_coordination import flags


def test_allowed_modes_exact():
    assert set(flags.ALLOWED_MODES) == {"off", "shadow", "rehearsal"}


def test_unknown_mode_resolves_off():
    env = {flags.MODE: "canary"}
    assert flags.multi_coord_mode(env) == "off"
    env = {flags.MODE: "live"}
    assert flags.multi_coord_mode(env) == "off"
    env = {flags.MODE: "l i v e"}
    assert flags.multi_coord_mode(env) == "off"


def test_mode_absent_is_off():
    assert flags.multi_coord_mode({}) == "off"
    assert flags.multi_coord_mode({"unrelated": "1"}) == "off"


def test_each_valid_mode_accepted():
    for m in ("off", "shadow", "rehearsal"):
        assert flags.multi_coord_mode({flags.MODE: m}) == m


def test_enabled_flag_strict_and_fail_closed():
    for v in ("true", "True", "TRUE", "1", "yes"):
        assert flags.multi_coord_enabled({flags.ENABLED: v}) is True
    for v in ("false", "0", "no", "garbage", ""):
        assert flags.multi_coord_enabled({flags.ENABLED: v}) is False
    assert flags.multi_coord_enabled({}) is False


def test_live_execution_permitted_is_always_false():
    assert flags.live_execution_permitted() is False
    assert flags.live_execution_permitted(
        {flags.ENABLED: "true", flags.MODE: "rehearsal"}
    ) is False