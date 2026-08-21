"""Test policy admission + negative matrix."""
from agent.service_restart_canary.allowlist import default_allowlist
from agent.service_restart_canary.policy import admission, AdmissionVerdict
from agent.service_restart_canary.negative_matrix import negative_matrix_ok, negative_matrix_results


_OK_PROFILE = {
    "service_class": "HERMES_AUXILIARY",
    "criticality": "LOW",
    "restart_supported": True,
}
_OK_CTX = {
    "identity_verified": True,
    "graph_status": "HEALTHY",
    "blast_radius": "SERVICE",
    "dependents": (),
    "consumer": "NO_RUNTIME_CONSUMER",
    "quiescence_proven": True,
    "startup_proven": True,
    "health_complete": True,
    "rollback_proven": True,
    "pre_health_ok": True,
    "executable_verified": True,
    "user_verified": True,
}


def test_canary_admitted():
    al = default_allowlist()
    r = admission("hermes-aux-canary", "hermes-aux-canary.service", al, _OK_PROFILE, _OK_CTX)
    assert r.verdict == AdmissionVerdict.ADMITTED


def test_unregistered_denied():
    al = default_allowlist()
    r = admission("ghost", "ghost.service", al, _OK_PROFILE, _OK_CTX)
    assert r.verdict == AdmissionVerdict.DENY


def test_gateway_denied():
    al = default_allowlist()
    r = admission("hermes-gateway", "hermes-gateway.service", al, _OK_PROFILE, _OK_CTX)
    assert r.verdict == AdmissionVerdict.DENY


def test_wrong_unit_denied():
    al = default_allowlist()
    r = admission("hermes-aux-canary", "wrong.service", al, _OK_PROFILE, _OK_CTX)
    assert r.verdict == AdmissionVerdict.DENY


def test_blast_multi_denied():
    al = default_allowlist()
    ctx = {**_OK_CTX, "blast_radius": "MULTI_SERVICE"}
    r = admission("hermes-aux-canary", "hermes-aux-canary.service", al, _OK_PROFILE, ctx)
    assert r.verdict == AdmissionVerdict.DENY


def test_prehealth_bad_denied():
    al = default_allowlist()
    ctx = {**_OK_CTX, "pre_health_ok": False}
    r = admission("hermes-aux-canary", "hermes-aux-canary.service", al, _OK_PROFILE, ctx)
    assert r.verdict == AdmissionVerdict.DENY


def test_negative_matrix_all_denied():
    al = default_allowlist()
    assert negative_matrix_ok(al) is True


def test_negative_matrix_count():
    al = default_allowlist()
    results = negative_matrix_results(al)
    assert len(results) >= 18
    for r in results:
        assert r.denied is True
