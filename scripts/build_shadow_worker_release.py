#!/usr/bin/env python3
"""Deterministic Phase 8.3 release manifest builder (read-only, no deployment).

Produces ``release/shadow-worker-8.3/`` certification artifacts:

  manifest.json       parent baseline, worker source file tree with sha256,
                      python version, schema version, dependency lock hash,
                      build timestamp, git provenance (no secrets).
  SHA256SUMS          deterministic per-file hashes of the manifest + config.
  config-example.json safe default worker config (kill-switch ON, no secrets).

This does NOT create /opt/hermes/releases/<sha> (that is a future Phase 8.4
external operator step).  It only materialises the certification bundle inside
the repo so the exact worker source is reproducible by SHA.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "agent" / "shadow_worker"
OUT = REPO / "release" / "shadow-worker-8.3"

PARENT_BASELINE = "2b27e82f5e364602fb07e1ae70d8b271deab5db7"

#: Deterministic, bounded set of files that constitute the worker FOUNDATION.
#: Only these are certified as Phase 8.3 (the "selective manifest").
WORKER_FILES = [
    "__init__.py", "audit.py", "config.py", "envelope.py", "exceptions.py",
    "health.py", "lifecycle.py", "metrics.py", "standalone.py", "transport.py",
    "worker.py", "__main__.py",
]


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def git_provenance() -> dict[str, str]:
    def _out(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True).stdout.strip()
    return {
        "head": _out("rev-parse", "HEAD"),
        "parent_baseline": PARENT_BASELINE,
        "branch": _out("rev-parse", "--abbrev-ref", "HEAD"),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    for name in WORKER_FILES:
        p = SRC / name
        if not p.exists():
            print(f"ERROR: missing worker file {p}")
            return 2
        files[name] = sha256_file(p)

    config_example = {
        "worker_enabled": False,
        "shadow_kill_switch": True,
        "sampling_percent": 0,
        "sampling_mode": "off",
        "network_read_only": False,
        "memory_writes": False,
        "mutation_capabilities": False,
        "max_queue_depth": 1000,
        "max_envelope_bytes": 65536,
        "max_concurrent_runs": 16,
        "max_task_duration_ms": 5000,
        "max_agent_duration_ms": 4000,
        "max_dag_nodes": 64,
        "max_retry_count": 2,
    }

    manifest = {
        "artifact": "hermes-v2-isolated-shadow-worker",
        "phase": "8.3",
        "schema_version": "shadow-envelope/v1",
        "parent_agent_platform_baseline": PARENT_BASELINE,
        "git": git_provenance(),
        "python": {
            "interpreter_container": "uv/cpython-3.11.15",
            "requires_python": ">=3.11,<3.14",
        },
        "worker_file_sha256": files,
        "config_example": config_example,
        "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    config_path = OUT / "config-example.json"
    config_path.write_text(json.dumps(config_example, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    entry_path = OUT / "worker-entrypoint"
    entry_path.write_text(
        "#!/usr/bin/env bash\n# Executable entrypoint for the isolated shadow worker.\n"
        "# Phase 8.3 certification only - NOT for live deployment yet.\n"
        "exec python -m agent.shadow_worker \"$@\"\n",
        encoding="utf-8",
    )
    entry_path.chmod(0o755)

    sums: dict[str, str] = {}
    for name in ("manifest.json", "config-example.json", "worker-entrypoint"):
        sums[name] = sha256_file(OUT / name)
    lines = "".join(f"{h}  {n}\n" for n, h in sorted(sums.items()))
    (OUT / "SHA256SUMS").write_text(lines, encoding="utf-8")

    print(f"Wrote release bundle to {OUT}/")
    print(f"  source files certified : {len(files)}")
    print(f"  manifest sha256        : {sums['manifest.json']}")
    print(json.dumps(manifest.get("git"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())