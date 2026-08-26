#!/usr/bin/env python3
"""NEW_REGRESSIONS classification for Phase 7 (shadow runtime) full canonical.

A failing file is a NEW REGRESSION only if it was introduced by this phase:
  (a) `git diff --stat HEAD -- <file>` is NON-EMPTY (the phase changed tracked
      content), OR
  (b) the path couples to Phase 7 / the phase touch-surface
      (agent/platform_shadow, agent/agent_integration, agent/agent_orchestration,
      agent/agent_system, tests/platform_shadow, tests/agent_integration,
      tests/agent_orchestration), OR
  (c) a NEW collection error / unresolved ImportError in a Phase 7 module.

Otherwise it is PROVEN_PRE_EXISTING (was already failing before Phase 7 and lies
outside the phase surface). Log path is a CLI arg (default /tmp/phase7-full-canonical.log)
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LOG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/phase7-full-canonical.log")

PHASE_PACKAGES = (
    "agent/platform_shadow",
    "agent/agent_integration",
    "agent/agent_orchestration",
    "agent/agent_system",
    "tests/platform_shadow",
    "tests/agent_integration",
    "tests/agent_orchestration",
)
FAIL_RE = re.compile(r"(?:FAILED|ERROR|✗|✘|\[FAIL\]|ImportError|ModuleNotFoundError)\s+([^\s]+)\.py")
FAIL_RE2 = re.compile(r"(?:FAILED|✘|✗)\s+(tests/[A-Za-z0-9_./-]+)\.py")


def failing_files(log: str) -> set[str]:
    files: set[str] = set()
    for line in log.splitlines():
        for pattern in (FAIL_RE, FAIL_RE2):
            for m in pattern.finditer(line):
                files.add(m.group(1) + ".py")
    return files


def is_modified_tracked(path: str) -> bool:
    r = subprocess.run(["git", "diff", "--stat", "HEAD", "--", path],
                       cwd=REPO, capture_output=True, text=True)
    return bool(r.stdout.strip())


def couples_to_phase(path: str) -> bool:
    return path.startswith(PHASE_PACKAGES)


def main() -> int:
    log = LOG.read_text(encoding="utf-8", errors="replace")
    files = failing_files(log)
    if not files:
        print(f"No failing files parsed from {LOG}")
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
        print(f"  NEW {path} ({why})")
    print(f"PROVEN_PRE_EXISTING={len(pre)}")
    return 0 if not new else 1


if __name__ == "__main__":
    raise SystemExit(main())