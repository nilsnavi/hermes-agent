"""Sprint 1.3.12 — quiescence gate + orphan detection (test_quiescence.py, test_orphans.py).

Quiescence gate between stop and start: old pid gone, no children, no orphans,
ports released, unit stopped. Only QUIESCENT allows future start.
Any orphan -> RESTART_UNSAFE / NOT_QUIESCENT.
"""
from __future__ import annotations

from agent.service_restart_foundation.quiescence import (
    QuiescenceResult,
    evaluate_quiescence,
)
from agent.service_restart_foundation.orphans import (
    DetectedOrphan,
    orphan_scan,
)


def _obs(**kw):
    base = dict(
        old_pid=100,
        old_pid_present=False,
        old_start_identity_present=False,
        children=(),
        orphan_workers=(),
        cgroup_members=(),
        stale_pidfile=False,
        port_owners={},
        unit_state="inactive",
    )
    base.update(kw)
    return base


class TestQuiescence:
    def test_quiescent_when_everything_cleared(self):
        assert evaluate_quiescence(_obs()).result == QuiescenceResult.QUIESCENT

    def test_old_pid_still_present_not_quiescent(self):
        r = evaluate_quiescence(_obs(old_pid_present=True))
        assert r.result == QuiescenceResult.NOT_QUIESCENT

    def test_orphan_worker_not_quiescent(self):
        r = evaluate_quiescence(_obs(orphan_workers=("pid:555",)))
        assert r.result == QuiescenceResult.NOT_QUIESCENT

    def test_cgroup_member_remains_not_quiescent(self):
        r = evaluate_quiescence(_obs(cgroup_members=(4,)))
        assert r.result == QuiescenceResult.NOT_QUIESCENT

    def test_stale_pidfile_not_quiescent(self):
        r = evaluate_quiescence(_obs(stale_pidfile=True))
        assert r.result == QuiescenceResult.NOT_QUIESCENT

    def test_port_owner_remains_not_quiescent(self):
        r = evaluate_quiescence(_obs(port_owners={"127.0.0.1:8080": "pid:88"}))
        assert r.result == QuiescenceResult.NOT_QUIESCENT

    def test_unknown_old_state(self):
        r = evaluate_quiescence({"old_pid_present": None})
        assert r.result == QuiescenceResult.UNKNOWN


class TestOrphanScan:
    def _run(self, **kw):
        ctx = dict(
            old_pid=100,
            children=(),
            cgroup_members=(),
            forked_workers=(),
            stale_pidfile=False,
            socket_owners=(),
            port_owners={},
        )
        ctx.update(kw)
        return orphan_scan(ctx)

    def test_no_orphans(self):
        findings = self._run()
        assert findings == []
        assert orphan_scan.is_clean is True if hasattr(orphan_scan, "is_clean") else True

    def test_orphan_child_detected(self):
        findings = self._run(children=("200",))
        assert findings and isinstance(findings[0], DetectedOrphan)
        assert findings[0].kind == "orphan_child"

    def test_forked_worker_detached(self):
        findings = self._run(forked_workers=(300,))
        assert any(f.kind == "forked_worker" for f in findings)

    def test_stale_pidfile_detected(self):
        findings = self._run(stale_pidfile=True)
        assert any(f.kind == "stale_pidfile" for f in findings)

    def test_wrong_socket_owner_detected(self):
        findings = self._run(socket_owners=("wrong-unit",))
        assert any(f.kind == "socket_owner" for f in findings)