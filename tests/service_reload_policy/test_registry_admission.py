"""Sprint 1.3.11 — registry, admission matrix, deny classes."""
from __future__ import annotations

import pytest

from agent.service_reload_policy import (AdmissionCheck, Blast, Class, Consumer,
                                         Criticality, ReloadRegistry, ReloadServiceProfile,
                                         admit, full_admit)


def _p(sid="aux1", cls=Class.AUXILIARY, crit=Criticality.LOW, blast=Blast.SERVICE,
       cons=Consumer.NONE, ere="/bin/kill -HUP $MAINPID", enabled=True,
       ver=True, graph=True, critdep=0, val=True, health=True, rollback=True):
    prof = ReloadServiceProfile(
        service_id=sid, profile_version=1, unit_name=f"{sid}.service",
        service_class=cls, criticality=crit,
        expected_user="hermes", expected_executable="handler.py",
        expected_exec_reload=ere, blast_radius_ceiling=blast,
        consumer=cons, enabled=enabled)
    chk = AdmissionCheck(identity_verified=ver, graph_healthy=graph,
                         critical_dependents=critdep, validator_exists=val,
                         health_contact_exists=health, rollback_proven=rollback)
    return prof, chk


def test_good_aux_admitted():
    prof, chk = _p()
    assert full_admit(prof, chk) is None


@pytest.mark.parametrize("cls", [Class.CORE, Class.DATASTORE, Class.SCHEDULER,
                                 Class.PROVIDER, Class.NETWORK, Class.SECURITY,
                                 Class.EXTERNAL, Class.UNKNOWN])
def test_denied_classes(cls):
    prof, chk = _p(cls=cls)
    assert full_admit(prof, chk) is not None


def test_registry_max_limit():
    r = ReloadRegistry()
    for i in range(3):
        r.register(_p(f"aux{i}", enabled=True)[0])
    with pytest.raises(RuntimeError):
        r.register(_p("aux4")[0])


def test_identity_unverified_deny():
    prof, chk = _p(ver=False)
    assert full_admit(prof, chk) == "IDENTITY_UNVERIFIED"


def test_graph_unhealthy_deny():
    prof, chk = _p(graph=False)
    assert full_admit(prof, chk) == "GRAPH_UNHEALTHY"


def test_critical_dependent_deny():
    prof, chk = _p(critdep=2)
    assert full_admit(prof, chk) == "CRITICAL_DEPENDENTS"


def test_validator_missing_deny():
    prof, chk = _p(val=False)
    assert full_admit(prof, chk) == "VALIDATOR_MISSING"


def test_rollback_missing_deny():
    prof, chk = _p(rollback=False)
    assert full_admit(prof, chk) == "ROLLBACK_UNPROVEN"


def test_missing_execreload_deny():
    prof, chk = _p(ere="")
    assert full_admit(prof, chk) == "NO_EXECRELOAD"