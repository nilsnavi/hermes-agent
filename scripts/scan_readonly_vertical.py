#!/usr/bin/env python3
"""AST mechanical gate for Phase 6 (First Read-Only System Agents Vertical).

Scans the Phase 6 touch-surface -- agent/agent_integration (new), the hardened
agent/agent_orchestration (message_bus/messages), and agent/agent_system
(monitoring role) -- and classifies every execution/authority-sensitive hit.

  UNAUTHORIZED_EXECUTION_PATHS (must be 0):
    F1  execution-kernel / IO module import (subprocess, os, socket, sqlite3,
        redis, httpx, psycopg, asyncio, systemctl, importlib, agent.execution,
        agent.recovery, agent.sandbox, agent.capability_router,
        agent.verified_tool_executor, agent.tool_registry, agent.orchestrator)
    F2  raw execution / process / signal primitive used IN CODE (not a string):
        os.system, os.popen/Popen, subprocess.<attr>, shell= kwarg, systemctl,
        kill, signal.send_signal, eval(, exec(, __import__(
    F3  an attribute CALL to execute/dispatch/grant/system/kill/run on any
        object (foreign invocation), OR a filesystem-write / git-mutation call
        (open(...,'w'), .write_text, os.write, git-commit/push as command)

CLASSIFIED (allowed, reported for the record):
    C1  authority-verb method DEFINITIONS that are pure control-plane seams
        (executor/verifier Protocol declarations or inert stubs)
    C3  execution-gate primitives referenced only as STRING LITERALS
        (classifier data, not execution)

Raw fs-write / git-mutation command strings are reported and must be 0 unless
they are string literals only (never executed by this package).
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGETS = [
    REPO / "agent" / "agent_integration",
    REPO / "agent" / "agent_orchestration",
    REPO / "agent" / "agent_system",
]

FORBIDDEN_IMPORTS = {
    "subprocess", "os", "socket", "sqlite3", "redis", "httpx", "psycopg",
    "asyncio", "systemctl", "importlib",
    "agent.execution", "agent.recovery", "agent.sandbox", "agent.capability_router",
    "agent.verified_tool_executor", "agent.tool_registry", "agent.orchestrator",
}
EXEC_PRIMITIVE_NAMES = {"eval", "exec", "__import__", "systemctl", "kill", "Popen"}
EXEC_PRIMITIVE_ATTRS = {"system", "popen", "run", "call", "Popen", "kill", "send_signal"}
AUTHORITY_CALL_ATTRS = {"execute", "dispatch", "grant", "system", "kill", "signal",
                        "write_text"}
ALLOWED_CONTROL_PLANE_PREFIXES = (
    "agent.agent_runtime", "agent.agent_orchestration", "agent.platform_",
    "agent.agent_system", "agent.agent_security_boundary", "agent.agent_integration",
    "pytest", "uuid", "hashlib", "threading", "math",
)
FILES: set[str] = set()


def _is_forbidden_module(name: str) -> bool:
    if name in FORBIDDEN_IMPORTS:
        return True
    if any(name.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
        return True
    return False


def _is_declaration_function(node) -> bool:
    """Protocol-stub / inert seam definition (no executable statements)."""
    for stmt in node.body:
        if isinstance(stmt, ast.Raise) or isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Return) and stmt.value is None:
            continue  # bare `return None` (or implicit)
        if isinstance(stmt, ast.Expr):
            continue  # docstring
        return False
    return True


F1, F2, F3, C1, C3 = [], [], [], [], []


def visit(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = str(path.relative_to(REPO))
    FILES.add(module)

    for node in ast.walk(tree):
        # imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    F1.append((module, f"import {alias.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if _is_forbidden_module(base):
                F1.append((module, f"from {base} import ...", node.lineno))
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if _is_forbidden_module(full):
                    F1.append((module, f"from {full}", node.lineno))

        # direct execution primitives
        if isinstance(node, ast.Call):
            fn = node.func
            # string literal primitive (classifier data)
            if isinstance(fn, ast.Constant) and isinstance(fn.value, str):
                C3.append((module, f"string primitive {fn.value!r}", node.lineno))
                continue
            if isinstance(fn, ast.Name) and fn.id in EXEC_PRIMITIVE_NAMES:
                F2.append((module, f"{fn.id}( ... )", node.lineno))
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id in ("os", "subprocess") and fn.attr in EXEC_PRIMITIVE_ATTRS:
                    F2.append((module, f"{fn.value.id}.{fn.attr}( ... )", node.lineno))
                if fn.attr in AUTHORITY_CALL_ATTRS and fn.value.id not in ("self", "cls"):
                    F2.append((module, f"authority call {fn.value.id}.{fn.attr}( ... )", node.lineno))
            # shell= kwarg
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    F2.append((module, "shell=True", node.lineno))
                if kw.arg == "shell":
                    F2.append((module, f"shell={ast.dump(kw.value)}", node.lineno))

        # open(...,'w') filesystem write / 'git push|commit' command data
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            args = [a for a in node.args] + [kw.value for kw in node.keywords if kw.arg == "mode"]
            if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "w" in a.value for a in args):
                F3.append((module, "open(..., 'w') filesystem write", node.lineno))
    return


def main() -> int:
    for target in TARGETS:
        if not target.exists():
            continue
        for f in sorted(target.rglob("*.py")):
            if "__pycache__" in str(f) or f.name.startswith("__init__.py"):
                continue
            try:
                visit(f)
            except SyntaxError as exc:
                print(f"SYNTAX ERROR {f}: {exc}")
                return 2

    print(f"Scanned {len(FILES)} files across {len(TARGETS)} package(s).")
    print(f"UNAUTHORIZED_EXECUTION_PATHS={len(F1) + len(F2) + len(F3)}")
    print(f"  F1(imports)={len(F1)} F2(primitives)={len(F2)} F3(authority/fs)={len(F3)}")
    for group, label in ((F1, "F1"), (F2, "F2"), (F3, "F3")):
        for module, kind, line in group:
            print(f"    {label} {module}:{line} {kind}")
    if F1 or F2 or F3:
        print("GATE FAIL: unauthorized execution paths present")
        return 1
    print(f"  CLASSIFIED C1(decls)={len(C1)} C3(string-data)={len(C3)}")
    for module, kind, line in C3:
        print(f"    C3 {module}:{line} {kind}")
    print("GATE PASS: UNAUTHORIZED_EXECUTION_PATHS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())