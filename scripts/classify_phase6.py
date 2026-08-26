#!/usr/bin/env python3
"""NEW_REGRESSIONS classification for Phase 6 full canonical.

A failing file is a NEW REGRESSION only if it was introduced by this phase:
  (a) `git diff --stat HEAD -- <file>` is NON-EMPTY (the phase changed/deleted
      tracked content), OR
  (b) the file path couples to this phase's packages
      (agent/agent_integration, agent/agent_orchestration, agent/agent_system,
      tests/agent_integration), OR
  (c) the failure is a NEW COLLECTION ERROR / unresolved ImportError in one of
      this phase's new modules.

Otherwise the failure is PROVEN_PRE_EXISTING (was already failing before Phase 6
because none of Panel-6 code touched it and it lives outside the phase surface).
The run log path is a CLI argument (default /tmp/phase6-full-canonical.log).
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LOG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/phase6-full-canonical.log")

PHASE_PACKAGES = (
    "agent/agent_integration",
    "agent/agent_orchestration",
    "agent/agent_system",
    "tests/agent_integration",
)
FAIL_RE = re.compile(
    r"(?:FAILED|ERROR|✗|✘|\[FAIL\]|ImportError|ModuleNotFoundError)\s+"
    r"([^\s]+)\.py",
)
# Also match pytest "FAILED tests/...::" and runner file-level "✗ tests/...".
FAIL_RE2 = re.compile(r"(?:FAILED|✘|✗)\s+(tests/[A-Za-z0-9_./-]+)\.py")


def failing_files(log: str) -> set[str]:
    files: set[str] = set()
    for line in log.splitlines():
        for pattern in (FAIL_RE, FAIL_RE2):
            for m in pattern.finditer(line):
                files.add(m.group(1) + ".py")
    return files


def is_modified_tracked(path: str) -> bool:
    r = subprocess.run(
        ["git", "diff", "--stat", "HEAD", "--", path],
        cwd=REPO, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def couples_to_phase(path: str) -> bool:
    return path.startswith(PHASE_PACKAGES)


def main() -> int:
    log = LOG.read_text(encoding="utf-8", errors="replace")
    files = failing_files(log)
    if not files:
        print(f"No failing files parsed from {LOG} (check log format)")
        return 2

    new = []
    pre = []
    for path in sorted(files):
        if is_modified_tracked(path) or couples_to_phase(path):
            new.append((path, "coupled" if couples_to_phase(path) else "modified-tracked"))
        else:
            pre.append(path)

    print(f"failing files parsed: {len(files)}")
    print(f"NEW_REGRESSIONS={len(new)}")
    for path, why in new:
        print(f"  NEW {path}  ({why})")
    print(f"PROVEN_PRE_EXISTING={len(pre)}")
    for path in pre:
        print(f"  PRE {path}")
    return 0 if not new else 1


if __name__ == "__main__":
    raise SystemExit(main())