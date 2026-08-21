"""Test flags: mode off/shadow/canary, unknown->off, flag no authority."""
import os
from agent.service_restart_canary import flags


def test_default_mode_off():
    assert flags.mode() == "off"


def test_default_disabled():
    assert flags.enabled() is False


def test_canary_active_default_false():
    assert flags.canary_active() is False


def test_mode_shadow():
    env = {flags.MODE: "shadow"}
    assert flags.mode(env) == "shadow"


def test_mode_canary():
    env = {flags.MODE: "canary"}
    assert flags.mode(env) == "canary"


def test_mode_unknown_off():
    env = {flags.MODE: "garbage"}
    assert flags.mode(env) == "off"


def test_canary_active_requires_both():
    assert flags.canary_active({flags.ENABLED: "true", flags.MODE: "canary"}) is True
    assert flags.canary_active({flags.ENABLED: "true", flags.MODE: "shadow"}) is False
    assert flags.canary_active({flags.ENABLED: "false", flags.MODE: "canary"}) is False


def test_flag_does_not_grant_authority():
    """Flag being true doesn't mean restart happens — executor kill-switch is separate."""
    assert flags.enabled({flags.ENABLED: "true"}) is True
    # But canary_active also needs mode=canary
    assert flags.canary_active({flags.ENABLED: "true"}) is False
