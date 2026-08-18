"""Sprint 1.3.7 live canary driver — ONE approved mutation at a time.

Usage: live_canary.py init   (create/refresh the baseline target file)
       live_canary.py run    (one approved mutation: generation N -> N+1)

Runs against the REAL production target through the agent/production_canary
pipeline (approved 78/78, sandbox rehearsal PASS).
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.production_canary.flags import Mode
from agent.production_canary.pipeline import ProductionCanaryPipeline
from agent.production_canary.schema import make_content, validate_content_bytes

TARGET = os.path.expanduser("~/.hermes/managed/canary/runtime-canary.json")
DIR = os.path.dirname(TARGET)
STORE = os.path.join(DIR, ".canarystore")
BASELINE = "8dfe9b3c82475e42e82e82fd1071991ad6e395ff"
#: Sprint 1.3.7 §27 hard caps.
MAX_SUCCESSFUL_PRODUCTION_MUTATIONS = 3


def init(force: bool = False):
    os.makedirs(DIR, exist_ok=True)
    os.chmod(DIR, 0o700)
    if force or not os.path.exists(TARGET):
        content = make_content(canary_id="runtime", generation=1, baseline_sha=BASELINE)
        _write_bytes(content)
    _print_state()


def _write_bytes(content: bytes):
    _atomic_atom(content)
    os.chmod(TARGET, 0o600)
    errs = validate_content_bytes(content)
    if errs:
        raise SystemExit(f"invalid init content: {errs}")


def _atomic_atom(content: bytes):
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".canary-", dir=DIR)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.rename(tmp, TARGET)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(gen: int, fault_verify: bool = False, requeue_idem: bool = False):
    if _kill_switch_active():
        raise SystemExit("KILL_SWITCH_ACTIVE: canary gate disabled")
    if _committed_mutations() >= MAX_SUCCESSFUL_PRODUCTION_MUTATIONS:
        raise SystemExit(f"ATTEMPT_LIMIT: {MAX_SUCCESSFUL_PRODUCTION_MUTATIONS} successful production mutations reached")
    p = ProductionCanaryPipeline(
        target=TARGET, owner=os.getlogin(), mode=Mode.CANARY, enabled=True,
        baseline_sha=BASELINE, store_dir=STORE,
    )
    r = p.run(approve=True, generation=gen, canary_id="runtime",
              fault_verify=fault_verify, requeue_idem=requeue_idem)
    if r["status"] == "COMMITTED":
        _bump_mutations()
    print("CANARY_RESULT", json.dumps(r, default=str))
    _print_state()
    return r


def _counters_path():
    return os.path.join(STORE, "counters.json")


def _committed_mutations():
    try:
        return json.load(open(_counters_path())).get("committed_mutations", 0)
    except Exception:
        return 0


def _bump_mutations():
    import tempfile
    n = _committed_mutations() + 1
    data = json.dumps({"committed_mutations": n, "kill_switch": "off"})
    os.makedirs(STORE, exist_ok=True)
    with open(_counters_path(), "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _kill_switch_active():
    try:
        return json.load(open(_counters_path())).get("kill_switch") == "on"
    except Exception:
        return False


def kill_switch():
    os.makedirs(STORE, exist_ok=True)
    n = _committed_mutations()
    with open(_counters_path(), "w") as f:
        f.write(json.dumps({"committed_mutations": n, "kill_switch": "on"}))
        f.flush()
        os.fsync(f.fileno())
    print("KILL_SWITCH_ON")


def _print_state():
    if os.path.exists(TARGET):
        import hashlib, stat
        st = os.stat(TARGET)
        data = open(TARGET, "rb").read()
        print("TARGET_STATE",
              json.dumps({
                  "generation": json.loads(data).get("generation"),
                  "sha256": hashlib.sha256(data).hexdigest()[:16],
                  "mode": oct(st.st_mode & 0o777),
                  "owner": pwd_owner(st.st_uid),
                  "islink": os.path.islink(TARGET),
              }))


def pwd_owner(uid):
    import pwd
    return pwd.getpwuid(uid).pw_name


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        init(force="force" in sys.argv)
    elif cmd == "reset":
        init(force=True)  # force a clean gen1 baseline
    elif cmd == "run":
        run(int(sys.argv[2]), fault_verify="fault" in sys.argv,
            requeue_idem="idem" in sys.argv)
    elif cmd == "killswitch":
        kill_switch()
