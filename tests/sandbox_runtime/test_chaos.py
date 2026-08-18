from __future__ import annotations
import pytest

from agent.sandbox_runtime.chaos import ChaosController, ChaosInjected, FaultPoint


def test_chaos_disabled_by_default():
    c = ChaosController()
    for point in FaultPoint:
        c.hit(point)


def test_enabled_chaos_is_deterministic():
    c = ChaosController(enabled=True, faults={FaultPoint.AFTER_PLAN})
    with pytest.raises(ChaosInjected):
        c.hit(FaultPoint.AFTER_PLAN)
    c.hit(FaultPoint.AFTER_PREFLIGHT)


def test_arbitrary_runtime_chaos_input_is_denied():
    with pytest.raises(ValueError):
        ChaosController.from_runtime("AFTER_PLAN", test_mode=False)


@pytest.mark.parametrize("point", list(FaultPoint))
def test_every_fault_point_is_injectable_in_test_mode(point):
    c = ChaosController.from_runtime(point.value, test_mode=True)
    with pytest.raises(ChaosInjected):
        c.hit(point)
