from __future__ import annotations

from agent.multi_service_coordination.execution_guard import (
    MULTI_SERVICE_EXECUTION_DISABLED,
    execution_disabled,
)
from agent.multi_service_coordination.flags import live_execution_permitted


def test_execution_always_disabled_even_with_valid_inputs():
    assert execution_disabled({}) == MULTI_SERVICE_EXECUTION_DISABLED
    assert execution_disabled(object()) == MULTI_SERVICE_EXECUTION_DISABLED
    assert execution_disabled() == MULTI_SERVICE_EXECUTION_DISABLED


def test_disabled_reason_string_exact():
    assert MULTI_SERVICE_EXECUTION_DISABLED == "MULTI_SERVICE_EXECUTION_DISABLED"


def test_live_execution_subject_to_flags_always_false():
    assert live_execution_permitted() is False
    assert live_execution_permitted(
        {"HERMES_MULTI_SERVICE_COORD_V2_ENABLED": "true",
         "HERMES_MULTI_SERVICE_COORD_V2_MODE": "rehearsal"}
    ) is False