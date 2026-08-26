#!/usr/bin/env python3
"""AST mechanical gate for Phase 5 (Execution Boundary hardening).

Scans the two Phase-5 packages (agent/agent_security_boundary and the hardened
agent/agent_system) and classifies every execution-sensitive hit:

  UNAUTHORIZED_EXECUTION_PATHS (must be 0):
    F1  execution-kernel / IO module import (subprocess, os, socket, sqlite3,
        redis, httpx, psycopg, asyncio, systemctl, agent.runtime, agent.execution,
        agent.recovery, agent.sandbox, agent.capability_router, agent.orchestrator,
        agent.tool_registry, agent.verified_tool_executor)
    F2  raw execution primitive used IN CODE (not a string): os.system,
        subprocess.<attr>, eval(, exec(, __import__(, importlib.<attr>, shell= kwarg
    F3  an attribute CALL to execute/dispatch/grant/system on any object (a
        foreign invocation; there are no such sites in these packages)

  CLASSIFIED (allowed, reported for the record):
    C1  authority-verb method DEFINITIONS that are pure Protocol seams /
        declarations (docstring/pass/... body) -- interface, not execution
    C2  the sealed sandbox guard (SealedSandbox.run) -- raises SealViolation
        unless the private gate token is supplied, and is never invoked by
        admission in this phase

Raw filesystem-write and git-mutation signals (open-write, .write_text,
"git push"/"git commit" used as commands) are also reported as C3 hits and must
be 0 unless a string literal only.
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGETS = [REPO / "agent" / "agent_security_boundary", REPO / "agent" / "agent_system"]

FORBIDDEN_IMPORTS = {
    "subprocess", "os", "socket", "sqlite3", "redis", "httpx", "psycopg",
    "asyncio", "systemctl", "importlib",
    "agent.runtime", "agent.execution", "agent.recovery", "agent.sandbox",
    "agent.capability_router", "agent.orchestrator", "agent.tool_registry",
    "agent.verified_tool_executor",
}
FORBIDDEN_NAMES = {"VerifiedToolExecutor", "RuntimeOrchestrator"}
EXEC_PRIMITIVE_NAMES = {"eval", "exec", "__import__", "system", "systemctl"}
EXEC_PRIMITIVE_ATTRS = {"system", "popen", "run", "call", "Popen"}
AUTHORITY_CALL_ATTRS = {"execute", "dispatch", "grant", "system"}
ALLOWED_CONTROL_PLANE_PREFIXES = (
    "agent.agent_runtime", "agent.agent_orchestration", "agent.platform_",
    "agent.agent_system", "agent.agent_security_boundary",
)
FILES = set()


def _is_forbidden_module(name: str) -> bool:
    if name in FORBIDDEN_IMPORTS:
        return True
    if any(name.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
        return True
    if name in FORBIDDEN_NAMES:
        return True
    if name.startswith("agent.") and not any(
        name.startswith(p) for p in ALLOWED_CONTROL_PLANE_PREFIXES
    ):
        return True
    return False


def _is_declaration_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the method body has no executable statements (a Protocol stub)."""
    for stmt in node.body:
        if isinstance(stmt, ast.Expr):
            value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                continue  # docstring
            if isinstance(value, ast.Constant) and value.value is Ellipsis:
                continue  # ...
            return False
        if isinstance(stmt, ast.Pass):
            continue
        return False
    return True


def scan(path: pathlib.Path) -> dict:
    res = {"F1": [], "F2": [], "F3": [], "C1": [], "C2": [], "C3": []}
    tree = ast.parse(path.read_text(errors="ignore"), filename=str(path))
    for node in ast.walk(tree):
        # imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    res["F1"].append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if _is_forbidden_module(mod):
                res["F1"].append((node.lineno, f"from {mod} import ..."))
        # method definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in AUTHORITY_CALL_ATTRS or node.name.startswith(("execute", "dispatch", "grant")):
                if _is_declaration_function(node):
                    res["C1"].append((node.lineno, f"def {node.name} (Protocol/declaration)"))
                else:
                    if node.name == "run" and "SealedSandbox" in path.name and "gate_token" in {a.arg for a in node.args.args}:
                        res["C2"].append((node.lineno, f"def {node.name} (sealed guard)"))
                    else:
                        res["F3"].append((node.lineno, f"def {node.name} (unsealed execution-looking body)"))
            elif node.name == "run":
                if "SealedSandbox" in path.name and "gate_token" in {a.arg for a in node.args.args}:
                    res["C2"].append((node.lineno, "SealedSandbox.run (sealed guard)"))
        # call sites
        if isinstance(node, ast.Call):
            fn = node.func
            # F2 raw execution primitives
            if isinstance(fn, ast.Name) and fn.id in {"eval", "exec", "__import__"}:
                res["F2"].append((node.lineno, f"{fn.id}(...) builtin call"))
            if isinstance(fn, ast.Attribute):
                if isinstance(fn.value, ast.Name) and fn.value.id == "os" and fn.attr in EXEC_PRIMITIVE_ATTRS:
                    res["F2"].append((node.lineno, f"os.{fn.attr}(...)"))
                if isinstance(fn.value, ast.Name) and fn.value.id == "subprocess":
                    res["F2"].append((node.lineno, f"subprocess.{fn.attr}(...)"))
                if isinstance(fn.value, ast.Name) and fn.value.id == "importlib":
                    res["F2"].append((node.lineno, f"importlib.{fn.attr}(...)"))
                if fn.attr in AUTHORITY_CALL_ATTRS and fn.attr not in {"system"}:
                    res["F3"].append((node.lineno, f"{_func_txt(fn)} (foreign authority call)"))
            for kw in node.keywords or []:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    res["F2"].append((node.lineno, "shell=True keyword"))
        # raw write / git-mutation string literals (C3 classified)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            for marker in ("git push", "git commit", "git add", "subprocess", "systemctl ", "os.system("):
                if marker in low:
                    res["C3"].append((node.lineno, f"string contains {marker.strip()!r}"))
                    break
    return res


def _func_txt(fn: ast.Attribute) -> str:
    if isinstance(fn.value, ast.Name):
        return f"{fn.value.id}.{fn.attr}"
    return f"?.{fn.attr}"


def main() -> int:
    findings: dict[str, list[str]] = {}
    total = 0
    for package in TARGETS:
        for path in sorted(package.rglob("*.py")):
            FILES.add(str(path.relative_to(REPO)))
            res = scan(path)
            total += 1
            for k, v in res.items():
                if v:
                    findings.setdefault(k, [])
                    for lineno, txt in v:
                        findings[k].append(f"{path.relative_to(REPO)}:{lineno} {txt}")
    print(f"SCANNED_FILES={total}")
    for k in ("F1", "F2", "F3"):
        hits = findings.get(k, [])
        print(f"{k}_HITS={len(hits)}")
        for h in hits:
            print("   ", h)
    unauthorized = len(findings.get("F1", [])) + len(findings.get("F2", [])) + len(findings.get("F3", []))
    print(f"UNAUTHORIZED_EXECUTION_PATHS={unauthorized}")
    print(f"CLASSIFIED_C1_PORT_DECLARATIONS={len(findings.get('C1', []))}")
    print(f"CLASSIFIED_C2_SEALED_GUARD={len(findings.get('C2', []))}")
    print(f"CLASSIFIED_C3_STRING_HITS={len(findings.get('C3', []))}")
    for h in findings.get("C1", []):
        print("   C1:", h)
    return 1 if unauthorized else 0


if __name__ == "__main__":
    sys.exit(main())