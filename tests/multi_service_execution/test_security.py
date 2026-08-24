"""Sprint 1.3.17 — security surface scan + authority-bypass scan."""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "agent" / "multi_service_execution"


def _all_source():
    return (list(PKG.glob("*.py")))


def _code_only(line: str) -> str:
    """Drop comments and string-literal contents so a deny-list of forbidden
    shapes (e.g. ``"raw-subprocess"``) does not trigger a false positive."""
    import re
    line = re.sub(r'"[^"]*"', '', line)
    line = re.sub(r"'[^']*'", '', line)
    line = line.split("#")[0]
    return line


def test_no_authority_leak_markers_in_production_source():
    forbidden = ["systemctl", "os.system", "shell=True", "eval(", "exec(",
                 "pickle.dumps", "yaml.load", "__import__", "subprocess"]
    for f in PKG.glob("*.py"):
        if f.name == "__init__.py":
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            stripped = _code_only(line)
            for marker in forbidden:
                assert marker not in stripped, f"{f.name}: {line}"


def test_no_secret_material_in_source():
    secret_pat = re.compile(
        r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
        r"Bearer\s+[A-Za-z0-9._-]{20,}|password\s*=\s*['\"][^'\"]+|"
        r"secret\s*=\s*['\"][^'\"]+|api_key\s*=\s*['\"][^'\"]+)")
    for f in _all_source():
        if f.name == "cli.py":
            continue  # cli has no such tokens either; guarded below
        for line in f.read_text(encoding="utf-8").splitlines():
            assert not secret_pat.search(line), f"{f.name}: {line}"


def test_no_dynamic_import_or_caller_executable_in_code():
    text = "\n".join(f.read_text() for f in _all_source() if f.name != "__init__.py")
    assert "__import__(" not in text
    assert "caller-provided" not in text


def test_no_runtime_state_in_production_source():
    for pat in (".db", ".wal", ".shm", ".txn", "/tmp", "state.db"):
        for f in _all_source():
            if f.name == "cli.py":
                continue
            # a durable-store root may legitimately default under ~/.hermes;
            # ensure no hardcoded absolute runtime state path leaks secrets
            text = f.read_text()
            assert "state.db" not in text


def test_public_api_excludes_executor_and_mint():
    import agent.multi_service_execution as m
    assert "BoundedMultiServiceExecutor" not in m.__all__
    assert not any("mint" in n.lower() for n in m.__all__)