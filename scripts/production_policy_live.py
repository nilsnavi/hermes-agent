"""Sprint 1.3.8 live driver — ONE approved limited mutation at a time (marker/json/rollback).

Usage:
  live.py setup                create marker/json resource dirs (700) + targets (600)
  live.py marker <name> <ENABLED|DISABLED>
  live.py json   <name> <json-string>
  live.py rollback <name> <ENABLED|DISABLED>   (injects verifier fault)
  live.py kill                  enable global limited-production kill switch
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.production_policy.policy import PolicyEngine
from agent.production_policy.runtime import LimitedPolicyRuntime
from agent.production_canary.atomic_write import content_hash

ROOT = os.path.expanduser("~/.hermes/managed/resources")
STORE = os.path.expanduser("~/.hermes/managed/resources/.policy-store")


def _engine():
    e = PolicyEngine(target_store_dir=STORE)
    # enable marker (and json) profiles for live
    e.profiles["P1-MARKER"] = dataclasses.replace(e.profiles["P1-MARKER"], enabled=True)
    e.profiles["P2-JSON"] = dataclasses.replace(e.profiles["P2-JSON"], enabled=True)
    # register live targets
    _reg(e, "P1-MARKER", "status")
    _reg(e, "P2-JSON", "config")
    return e


def _reg(e, pid, name):
    from agent.production_policy.models import TargetRegistration
    prof = e.profiles[pid]
    base = prof.exact_target_dir.rstrip(os.sep)
    path = os.path.join(base, name + ".json")
    e.targets[pid][name] = TargetRegistration(
        profile_id=pid, target_id=name, resolved_path=path, realpath=os.path.realpath(path),
        owner="hermes", mode=0o600)


def _resolved(e):
    m = {}
    for pid, d in e.targets.items():
        for name, t in d.items():
            m[name] = t.resolved_path
    return m


def _appr(profile, op, name, ph):
    return {"profile": profile, "profile_version": 1, "operation": op,
            "target": name, "payload_hash": ph, "expires_ts": time.time() + 600}


def setup():
    for sub in ("markers", "json", "text"):
        d = os.path.join(ROOT, sub)
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o700)
        print("dir", d, oct(os.stat(d).st_mode & 0o777))
    e = _engine()
    for pid, name in (("P1-MARKER", "status"), ("P2-JSON", "config")):
        p = e.targets[pid][name].resolved_path
        if not os.path.exists(p):
            data = b"ENABLED" if pid == "P1-MARKER" else json.dumps(
                {"schema_version": 1, "enabled": False}, indent=2).encode()
            _atomic(p, data)
            os.chmod(p, 0o600)
        print("target", p, "mode", oct(os.stat(p).st_mode & 0o777))


def _atomic(p, data):
    import tempfile
    d = os.path.dirname(p)
    fd, tmp = tempfile.mkstemp(prefix=".pp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.rename(tmp, p)
        dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _killed():
    try:
        return open(os.path.join(STORE, "kill.txt")).read().strip() == "off"
    except OSError:
        return False


def run_marker(name, value, fault=False):
    if _killed():
        raise SystemExit("POLICY_KILLED: limited-production gate disabled")
    e = _engine()
    rt = LimitedPolicyRuntime(engine=e, store_dir=STORE, resolved=_resolved(e),
                              idem_path=os.path.join(STORE, "idem.json"))
    ph = content_hash(value.encode())
    r = rt.run(profile_id="P1-MARKER", target=name, operation="set_marker",
               payload=value.encode(), approval=_appr("P1-MARKER", "set_marker", name, ph),
               resource_mode="limited", fault_verify=fault, idem=f"m:{name}:{value}")
    print("MARKER_RESULT", json.dumps(r, default=str))
    return r


def run_json(name, payload_str, fault=False):
    if _killed():
        raise SystemExit("POLICY_KILLED: limited-production gate disabled")
    e = _engine()
    rt = LimitedPolicyRuntime(engine=e, store_dir=STORE, resolved=_resolved(e),
                              idem_path=os.path.join(STORE, "idem.json"))
    payload = payload_str.encode()
    ph = content_hash(payload)
    r = rt.run(profile_id="P2-JSON", target=name, operation="update_json",
               payload=payload, approval=_appr("P2-JSON", "update_json", name, ph),
               resource_mode="limited", fault_verify=fault, idem=f"j:{name}")
    print("JSON_RESULT", json.dumps(r, default=str))
    return r


def kill():
    os.makedirs(STORE, exist_ok=True)
    with open(os.path.join(STORE, "kill.txt"), "w") as f:
        f.write("off"); f.flush(); os.fsync(f.fileno())
    print("POLICY_KILL_SWITCH_ON")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "setup":
        setup()
    elif cmd == "marker":
        run_marker(sys.argv[2], sys.argv[3], fault="fault" in sys.argv)
    elif cmd == "json":
        run_json(sys.argv[2], sys.argv[3], fault="fault" in sys.argv)
    elif cmd == "kill":
        kill()
