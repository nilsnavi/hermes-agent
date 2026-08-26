#!/usr/bin/env python3
"""NEW_REGRESSIONS classification for Phase 5 full canonical.

A failing file is a NEW REGRESSION only if it was introduced by this phase:
  (a) `git diff --stat HEAD -- <file>` is NON-EMPTY (phase touched it), AND/OR
  (b) it couples to agent_security_boundary / agent_system, OR
  (c) it lives under tests/agent_security_boundary or tests/agent_system.
A file that is untouched by the phase (empty diff) and uncoupled is PROVEN
PRE-EXISTING. NEW_REGRESSIONS = |non_empty_diff_or_missing ∪ coupled|.
"""
import pathlib
import re
import subprocess

REPO = pathlib.Path("/home/hermes/.hermes/hermes-agent-sprint137")
LOG = pathlib.Path("/tmp/phase5-full-canonical.log")

# Candidates to be touched by Phase 5.
PHASE_NS = ("agent/agent_security_boundary", "agent/agent_system")
PHASE_TEST_NS = ("tests/agent_security_boundary", "tests/agent_system")


def _git_diff_empty(rel: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--stat", "HEAD", "--", rel],
        capture_output=True, text=True,
    )
    return proc.stdout.strip() == ""


def main() -> int:
    log_text = LOG.read_text(errors="ignore")
    failing: set[str] = set()
    # Runner per-file failure markers: "✗ tests/foo.py (n failed)" or "FAILED tests/..."
    for match in re.finditer(r"FAILED\s+(tests/[^\s]+\.py)", log_text):
        failing.add(match.group(1))
    for match in re.finditer(r"(?:✗|✘|\[FAIL\])\s+(tests/[^\s]+\.py)", log_text):
        failing.add(match.group(1))
    for line in log_text.splitlines():
        if "FAILED" in line or " failed" in line or "errors" in line.lower():
            m = re.search(r"(tests/\S+\.py)", line)
            if m:
                failing.add(m.group(1))

    total_files: int = 0
    m = re.search(r"(\d+) files", log_text)
    if m:
        total_files = int(m.group(1))

    nonempty_diff = []
    coupled = []
    phase_test_in_fail = []
    proven_pre_existing = []

    for rel in sorted(failing):
        path = REPO / rel
        empty = _git_diff_empty(rel)
        is_phase_test = rel.startswith(PHASE_TEST_NS) or any(
            _phase_ns in rel for _phase_ns in PHASE_NS
        ) or rel.startswith("tests/agent_system")
        coupled_flag = False
        if path.exists():
            text = path.read_text(errors="ignore")
            coupled_flag = any(ns in text for ns in PHASE_NS)
        elif is_phase_test:
            nonempty_diff.append(rel)  # missing-but-phase-owned -> flag
            continue
        if not empty:
            nonempty_diff.append(rel)
        if coupled_flag:
            coupled.append(rel)
        if is_phase_test:
            phase_test_in_fail.append(rel)
        if empty and not coupled_flag and not is_phase_test:
            proven_pre_existing.append(rel)

    new_regressions = sorted(
        set(nonempty_diff) | set(coupled) | set(phase_test_in_fail)
    )
    print(f"LOG={LOG}")
    print(f"TOTAL_FILES={total_files}")
    print(f"FAILING_FILE_COUNT={len(failing)}")
    print(f"NON_EMPTY_DIFF_OR_MISSING={len(nonempty_diff)} -> {nonempty_diff}")
    print(f"COUPLED_TO_AGENT_BOUNDARY={len(coupled)} -> {coupled}")
    print(f"PHASE_TEST_FILES_IN_FAILURES={len(phase_test_in_fail)} -> {phase_test_in_fail}")
    print(f"PROVEN_PRE_EXISTING={len(proven_pre_existing)}")
    print(f"NEW_REGRESSIONS={len(new_regressions)} -> {new_regressions}")
    return 0 if not new_regressions else 1


if __name__ == "__main__":
    raise SystemExit(main())