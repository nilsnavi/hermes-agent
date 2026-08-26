#!/usr/bin/env python3
"""Mechanical gate for Phase 8 production shadow hook + the bounce surface.

Scans agent/production_shadow_hook, agent/platform_shadow, agent/agent_integration,
agent/agent_orchestration and agent/agent_system and proves:

  UNAUTHORIZED_EXECUTION_PATHS = 0 (no subprocess/os.system/shell/systemctl/kill/
     signal/eval/exec / execution-kernel+scheduler+provider+gateway+response imports)
  PRODUCTION_OVERRIDE_PATHS    = 0 (no override/activate/grant/authorize surface)
  PRODUCTION_MUTATION_PATHS    = 0 (no filesystem-write / git mutation / response write)
  PRODUCTION_RETURN_PATHS      = 0 (no apply_shadow_result / replace_response /
     override_decision / retry_with_shadow / promote_shadow_result surface)
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGETS = [
    REPO / "agent" / "production_shadow_hook",
    REPO / "agent" / "platform_shadow",
    REPO / "agent" / "agent_integration",
    REPO / "agent" / "agent_orchestration",
    REPO / "agent" / "agent_system",
]

FORBIDDEN_IMPORTS = {
    "subprocess", "socket", "sqlite3", "redis", "httpx", "psycopg",
    "asyncio", "systemctl", "importlib", "signal",
    "agent.execution", "agent.recovery", "agent.sandbox", "agent.capability_router",
    "agent.verified_tool_executor", "agent.tool_registry", "agent.orchestrator",
    "agent.scheduler", "agent.provider_config", "agent.gateway", "agent.response",
}
EXEC_PRIMITIVES = {"eval", "exec", "__import__", "systemctl", "kill", "Popen", "send_signal"}
EXEC_ATTRS = {"system", "popen", "run", "call", "Popen", "kill", "send_signal", "systemctl"}
OVERRIDE_ATTRS = {"execute", "grant", "system", "kill", "signal", "write_text",
                  "override", "activate", "authorize", "replace_production", "dispatch_production"}
# Shadow -> production return surfaces: these APIs MUST NOT exist anywhere.
RETURN_APIS = {"apply_shadow_result", "replace_response", "override_decision",
               "retry_with_shadow", "promote_shadow_result", "apply", "promote"}
OVERRIDE_READS = {"override", "replace_production", "production_override",
                  "approval_token", "execution_token", "approve", "grant"}
FILES: set[str] = set()
F1, F2, F3, MUT, RET = [], [], [], [], []


def _forbidden(name):
    if name in FORBIDDEN_IMPORTS or any(name.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
        return True
    return False


def visit(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = str(path.relative_to(REPO))
    FILES.add(module)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _forbidden(a.name):
                    F1.append((module, f"import {a.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if _forbidden(base):
                F1.append((module, f"from {base}", node.lineno))
            for a in node.names:
                if _forbidden(f"{base}.{a.name}" if base else a.name):
                    F1.append((module, f"from {a.name}", node.lineno))

        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in EXEC_PRIMITIVES:
                F2.append((module, f"{fn.id}(..)", node.lineno))
            if isinstance(fn, ast.Attribute):
                if isinstance(fn.value, ast.Name) and fn.value.id in ("os", "subprocess") \
                        and fn.attr in EXEC_ATTRS:
                    F2.append((module, f"{fn.value.id}.{fn.attr}(..)", node.lineno))
                if fn.attr in OVERRIDE_ATTRS and (
                        not isinstance(fn.value, ast.Name) or fn.value.id not in ("self", "cls")):
                    F3.append((module, f"override call {ast.unparse(fn)[:60]}", node.lineno))
                if fn.attr in RETURN_APIS:
                    RET.append((module, f"shadow->production return surface {fn.attr}", node.lineno))
            for kw in node.keywords:
                if kw.arg == "shell":
                    F2.append((module, f"shell={ast.unparse(kw.value)[:40]}", node.lineno))
            if isinstance(fn, ast.Name) and fn.id == "open":
                args = [a for a in node.args] + [k.value for k in node.keywords if k.arg == "mode"]
                if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "w" in a.value
                       for a in args):
                    MUT.append((module, "open(...,'w') filesystem write", node.lineno))
            continue

        if isinstance(node, ast.Attribute):
            if node.attr in OVERRIDE_READS and (
                    not isinstance(node.value, ast.Name) or node.value.id not in ("self", "cls")):
                MUT.append((module, f"override surface read {node.attr}", node.lineno))
            if node.attr in RETURN_APIS:
                RET.append((module, f"shadow->production return ref {node.attr}", node.lineno))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RETURN_APIS:
            RET.append((module, f"def {node.name}()", node.lineno))


def main() -> int:
    for target in TARGETS:
        if target.exists():
            for f in sorted(target.rglob("*.py")):
                if "__pycache__" in str(f):
                    continue
                visit(f)
    print(f"Scanned {len(FILES)} files across {len(TARGETS)} package(s).")
    print(f"UNAUTHORIZED_EXECUTION_PATHS={len(F1)+len(F2)+len(F3)} (F1={len(F1)} F2={len(F2)} F3={len(F3)})")
    print(f"PRODUCTION_OVERRIDE_PATHS={len(F3)}  PRODUCTION_MUTATION_PATHS={len(MUT)}  PRODUCTION_RETURN_PATHS={len(RET)}")
    for label, g in (("F1", F1), ("F2", F2), ("F3", F3), ("MUT", MUT), ("RET", RET)):
        for m, k, ln in g:
            print(f"    {label} {m}:{ln} {k}")
    if F1 or F2 or F3 or MUT or RET:
        print("GATE FAIL")
        return 1
    print("GATE PASS: UNAUTHORIZED_EXECUTION_PATHS=0 PRODUCTION_OVERRIDE_PATHS=0 PRODUCTION_MUTATION_PATHS=0 PRODUCTION_RETURN_PATHS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())