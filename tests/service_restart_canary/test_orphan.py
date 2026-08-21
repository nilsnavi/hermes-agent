"""Test orphan detection: any orphan -> RESTART_UNSAFE.
Uses the foundation orphan_scan contract keys (children/cgroup_members/...).
"""
from agent.service_restart_canary.verify import orphan_check
from agent.service_restart_foundation.orphans import orphan_scan


def test_no_orphans():
    r = orphan_check({"children": (), "cgroup_members": (), "forked_workers": ()})
    assert r.ok is True


def test_orphan_child():
    r = orphan_check({"children": ("c1",)})
    assert r.ok is False


def test_cgroup_member():
    r = orphan_check({"cgroup_members": ("m1",)})
    assert r.ok is False


def test_forked_worker():
    r = orphan_check({"forked_workers": ("w1",)})
    assert r.ok is False


def test_stale_pidfile():
    r = orphan_check({"stale_pidfile": True})
    assert r.ok is False


def test_orphan_scan_returns_kinds():
    findings = orphan_scan({"children": ("c1",), "cgroup_members": ("m1",),
                            "forked_workers": ("w1",)})
    assert len(findings) >= 3
    kinds = {f.kind for f in findings}
    assert "orphan_child" in kinds
    assert "cgroup_member" in kinds
    assert "forked_worker" in kinds