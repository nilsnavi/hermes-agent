#!/usr/bin/env python3
"""Mechanical gate for Phase 7 shadow runtime + the control-plane surface it reuses.

Proves two invariants over agent/platform_shadow, agent/agent_integration,
agent/agent_orchestration and agent/agent_system:

  UNAUTHORIZED_EXECUTION_PATHS (must be 0):  imports of execution-kernel / IO /
     scheduler / provider-config / gateway modules, raw execution primitives
     (subprocess, os.system, popen, shell=True, systemctl, kill, signal, eval,
     exec), authority-verb calls, and filesystem-write / git-mutation.
  PRODUCTION_OVERRIDE_PATHS (must be 0): any reference that could return, mutate
     or override a production result, grant authority, or change scheduler /
     provider / gateway state. The shadow package is allowed to REUSE the
     read-only vertical (agent_integration), but must expose no override surface.
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGETS = [
    REPO / "agent" / "platform_shadow",
    REPO / "agent" / "agent_integration",
    REPO / "agent" / "agent_orchestration",
    REPO / "agent" / "agent_system",
]

FORBIDDEN_IMPORTS = {
    "subprocess", "os", "socket", "sqlite3", "redis", "httpx", "psycopg",
    "asyncio", "systemctl", "importlib", "signal",
    "agent.execution", "agent.recovery", "agent.sandbox", "agent.capability_router",
    "agent.verified_tool_executor", "agent.tool_registry", "agent.orchestrator",
    "agent.scheduler", "agent.provider_config", "agent.gateway", "agent.response",
    "agent.recovery_runtime",
}
EXEC_PRIMITIVE_NAMES = {"eval", "exec", "__import__", "systemctl", "kill", "Popen",
                        "send_signal"}
EXEC_PRIMITIVE_ATTRS = {"system", "popen", "run", "call", "Popen", "kill",
                        "send_signal", "systemctl"}
# Authority / production-override call attrs: any ATTRIBUTE call with these names
# on a non-self object is a forbidden path (override/replace_production/
# activate/grant...). Deliberately NOT 'dispatch' (shadow-side entry) or
# 'replace'/'authorize' (legit str/dataclass or seam definitions).
AUTHORITY_CALL_ATTRS = {"execute", "grant", "system", "kill", "signal",
                        "write_text", "override", "activate",
                        "replace_production", "dispatch_production"}
# Attribute accesses (member reads) that indicate holding a production override
# surface -- flagged as PRODUCTION_OVERRIDE_PATHS (must be 0).
OVERRIDE_ATTR_READS = {"override", "replace_production", "production_override",
                       "approval_token", "execution_token", "approve", "grant"}
ALLOWED_CONTROL_PLANE_PREFIXES = (
    "agent.agent_runtime", "agent.agent_orchestration", "agent.platform_memory",
    "agent.platform_policy", "agent.agent_system", "agent.agent_security_boundary",
    "agent.agent_integration", "agent.platform_shadow",
)
FILES: set[str] = set()

F1, F2, F3, P1 = [], [], [], []  # imports, primitives, authority/fs, production-override


def _is_forbidden_module(name: str) -> bool:
    if name in FORBIDDEN_IMPORTS:
        return True
    if any(name.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
        return True
    return False


def visit(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = str(path.relative_to(REPO))
    FILES.add(module)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    F1.append((module, f"import {alias.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if _is_forbidden_module(base):
                F1.append((module, f"from {base} import ...", node.lineno))
            for alias in node.names:
                if _is_forbidden_module(f"{base}.{alias.name}" if base else alias.name):
                    F1.append((module, f"from {alias.name}", node.lineno))

        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in EXEC_PRIMITIVE_NAMES:
                F2.append((module, f"{fn.id}( ... )", node.lineno))
            if isinstance(fn, ast.Attribute):
                if isinstance(fn.value, ast.Name) and fn.value.id in ("os", "subprocess") \
                        and fn.attr in EXEC_PRIMITIVE_ATTRS:
                    F2.append((module, f"{fn.value.id}.{fn.attr}( ... )", node.lineno))
                if fn.attr in AUTHORITY_CALL_ATTRS and (
                        not isinstance(fn.value, ast.Name) or fn.value.id not in ("self", "cls")):
                    F3.append((module, f"authority/override call {ast.dump(fn)}", node.lineno))
            for kw in node.keywords:
                if kw.arg == "shell":
                    F2.append((module, f"shell={ast.dump(kw.value)}", node.lineno))
            if isinstance(fn, ast.Name) and fn.id == "open":
                args = [a for a in node.args] + [k.value for k in node.keywords if k.arg == "mode"]
                if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "w" in a.value
                       for a in args):
                    F3.append((module, "open(..., 'w') filesystem write", node.lineno))
            continue

        # Production-override surface held via a member access (not a call).
        if isinstance(node, ast.Attribute):
            if node.attr in OVERRIDE_ATTR_READS and (
                    not isinstance(node.value, ast.Name) or node.value.id not in ("self", "cls")):
                P1.append((module, f"override surface read {node.attr}", node.lineno))


def main() -> int:
    for target in TARGETS:
        if not target.exists():
            continue
        for f in sorted(target.rglob("*.py")):
            if "__pycache__" in str(f):
                continue
            try:
                visit(f)
            except SyntaxError as exc:
                print(f"SYNTAX ERROR {f}: {exc}")
                return 2

    print(f"Scanned {len(FILES)} files across {len(TARGETS)} package(s).")
    uep = len(F1) + len(F2) + len(F3)
    print(f"UNAUTHORIZED_EXECUTION_PATHS={uep}  (F1={len(F1)} F2={len(F2)} F3={len(F3)})")
    print(f"PRODUCTION_OVERRIDE_PATHS={len(P1)}")
    for group, label in ((F1, "F1"), (F2, "F2"), (F3, "F3")):
        for module, kind, line in group:
            print(f"    {label} {module}:{line} {kind}")
    for module, kind, line in P1:
        print(f"    P1 {module}:{line} {kind}")
    if F1 or F2 or F3 or P1:
        print("GATE FAIL")
        return 1
    print("GATE PASS: UNAUTHORIZED_EXECUTION_PATHS=0 PRODUCTION_OVERRIDE_PATHS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())