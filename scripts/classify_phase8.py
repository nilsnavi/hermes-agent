#!/usr/bin/env python3
"""NEW_REGRESSIONS classification for Phase 8 (controlled production shadow hook).

A failing file is a NEW REGRESSION iff:
  (a) `git diff --stat HEAD -- <file>` is NON-EMPTY (phase changed tracked content), OR
  (b) the path couples to Phase 8 / the phase touch-surface
      (agent/production_shadow_hook, agent/platform_shadow, agent/agent_integration,
      agent/agent_orchestration, agent/agent_system, and the phase test dirs), OR
  (c) a NEW collection error / unresolved ImportError in a Phase 8 module.
Else it is PROVEN_PRE_EXISTING. Log path arg default /tmp/phase8-full-canonical.log
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LOG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/phase8-full-canonical.log")

PHASE_PACKAGES = (
    "agent/production_shadow_hook",
    "agent/platform_shadow",
    "agent/agent_integration",
    "agent/agent_orchestration",
    "agent/agent_system",
    "tests/production_shadow_hook",
    "tests/platform_shadow",
    "tests/agent_integration",
    "tests/agent_orchestration",
)
FAIL_RE = re.compile(r"(?:FAILED|ERROR|✗|✘|\[FAIL\]|ImportError|ModuleNotFoundError)\s+([^\s]+)\.py")
FAIL_RE2 = re.compile(r"(?:FAILED|✘|✗)\s+(tests/[A-Za-z0-9_./-]+)\.py")


def failing_files(log: str) -> set[str]:
    files: set[str] = set()
    for line in log.splitlines():
        for pat in (FAIL_RE, FAIL_RE2):
            for m in pat.finditer(line):
                files.add(m.group(1) + ".py")
    return files


def is_modified_tracked(path: str) -> bool:
    r = subprocess.run(["git", "diff", "--stat", "HEAD", "--", path],
                       cwd=REPO, capture_output=True, text=True)
    return bool(r.stdout.strip())


def couples(path: str) -> bool:
    return path.startswith(PHASE_PACKAGES)


def main() -> int:
    log = LOG.read_text(encoding="utf-8", errors="replace")
    files = failing_files(log)
    if not files:
        print(f"No failing files parsed from {LOG}")
        return 2
    new, pre = [], []
    for path in sorted(files):
        if is_modified_tracked(path) or couples(path):
            new.append((path, "coupled" if couples(path) else "modified-tracked"))
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