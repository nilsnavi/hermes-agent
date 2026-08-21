"""Test shadow: >=50 evaluations, candidate correctness 100%, 0 mutations."""
from agent.service_restart_canary.shadow import (run_shadow_evaluations, shadow_pass,
                                                  shadow_mutation_calls)
from agent.service_restart_canary.allowlist import default_allowlist


def test_shadow_evaluations_50():
    results = run_shadow_evaluations(n=50)
    assert len(results) >= 50


def test_shadow_default_50():
    assert len(run_shadow_evaluations()) >= 50


def test_shadow_pass():
    assert shadow_pass(run_shadow_evaluations(n=50)) is True


def test_shadow_zero_mutation():
    assert shadow_mutation_calls() == 0
    for r in run_shadow_evaluations(n=50):
        assert r.mutations == 0


def test_shadow_correctness():
    """Only canary case admitted; all deny variants denied."""
    for r in run_shadow_evaluations(n=70):
        if r.case == "canary_ok":
            assert r.admitted is True
        else:
            assert r.admitted is False