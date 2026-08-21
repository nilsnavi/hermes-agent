"""Test negative matrix: every denied case must be denied, 0 mutations."""
from agent.service_restart_canary.allowlist import default_allowlist
from agent.service_restart_canary.negative_matrix import negative_matrix_ok, negative_matrix_results


def test_negative_matrix_ok():
    assert negative_matrix_ok(default_allowlist()) is True


def test_negative_matrix_covers_cases():
    al = default_allowlist()
    results = negative_matrix_results(al)
    names = {r.case for r in results}
    for required in ("unregistered_service", "gateway", "scheduler", "provider",
                     "database", "network", "security", "unknown_service",
                     "wrong_unit", "wrong_identity", "wrong_executable", "wrong_user",
                     "graph_stale", "blast_multiservice", "dependents_present",
                     "prehealth_bad", "quiescence_unproven", "rollback_unproven"):
        assert required in names, f"missing case {required}"


def test_all_denied():
    for r in negative_matrix_results(default_allowlist()):
        assert r.denied is True, f"{r.case} should be denied"