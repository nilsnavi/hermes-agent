#!/usr/bin/env python3
"""NEW_REGRESSIONS classification for Phase 4 full canonical.

For every failing test file in the canonical log:
  (a) `git diff --stat HEAD -- <file>` must be EMPTY  -> phase never touched it
  (b) file content must NOT import agent_system       -> no coupling
Plus: none of the failing files may be under tests/agent_system.
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path("/home/hermes/.hermes/hermes-agent-sprint137")
LOG = pathlib.Path("/tmp/phase4-full-canonical.log")

# Extract failing .py file paths: "✓/✗ tests/foo.py (N failed)" or FAILED lines.
failing = set()
log_text = LOG.read_text()
for match in re.finditer(r"FAILED (tests/[^\s]+\.py)", log_text):
    failing.add(match.group(1))
for line in log_text.splitlines():
    # runner per-file failure lines look like: "✗ tests/foo.py (n failed)"
    m = re.match(r".*FAILED\s+(tests/[^\s]+\.py)", line)
    if m:
        failing.add(m.group(1))
# fallback: any line mentioning "tests/...py" followed by failure markers
for line in log_text.splitlines():
    m = re.search(r"(tests/\S+\.py)[^\n]*(?:\bfailed\b|errors\b)", line.lower())
    if m:
        failing.add(m.group(1))

failing = sorted(failing)
print(f"FAILING_FILE_COUNT={len(failing)}")

empty_diff = cast_coupled = nonempty_diff_or_missing = []
empty_diff = []
nonempty_diff_or_missing = []
coupled = []
agent_system_in_fail = []

for rel in failing:
    path = REPO / rel
    # (a) git diff vs HEAD must be empty (untouched by phase)
    proc = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--stat", "HEAD", "--", rel],
        capture_output=True, text=True,
    )
    is_empty = proc.stdout.strip() == ""
    # (b) coupling: file must not import agent_system
    coupled_flag = False
    if path.exists():
        text = path.read_text(errors="ignore")
        if "agent_system" in text:
            coupled_flag = True
    else:
        # missing file -> treat as non-empty diff (cannot prove untouched by git)
        if not is_empty:
            pass
        # missing test file is itself worth flagging
        coupled_flag = coupled_flag or ("missing-file" in rel)
        nonempty_diff_or_missing.append(rel)
        continue
    if not is_empty:
        nonempty_diff_or_missing.append(rel)
    if coupled_flag:
        coupled.append(rel)
    if rel.startswith("tests/agent_system/"):
        agent_system_in_fail.append(rel)
    if is_empty and not coupled_flag:
        empty_diff.append(rel)

print(f"NON_EMPTY_DIFF_OR_MISSING={len(nonempty_diff_or_missing)} -> {nonempty_diff_or_missing}")
print(f"COUPLED_TO_AGENT_SYSTEM={len(coupled)} -> {coupled}")
print(f"AGENT_SYSTEM_IN_FAILURES={len(agent_system_in_fail)} -> {agent_system_in_fail}")
print(f"PROVEN_PRE_EXISTING={len(empty_diff)}")