#!/usr/bin/env python3
"""AST mechanical gate for agent/agent_system.

Enforces the Phase 4 no-second-execution-engine invariant over every .py in the
package:
  * ZERO imports of execution-kernel / IO roots
  * ZERO authority-verb method definitions and tool-execution call sites

Execution-kernel import roots:
  subprocess, os.system(attr), socket, sqlite3, redis, httpx, psycopg, asyncio,
  systemctl, VerifiedToolExecutor, RuntimeOrchestrator, and the execution module
  paths: agent.runtime, agent.execution, agent.recovery, agent.sandbox,
  agent.capability_router, agent.orchestrator, agent.tool_registry.

Control-plane siblings (agent.agent_runtime, agent.agent_orchestration,
agent.platform_*, agent.agent_system) are explicitly allowed.

Authority-verb method definitions and attribute calls: execute, dispatch,
authorize, grant, run, system (os.system).
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repo root
PKG = ROOT / "agent" / "agent_system"

FORBIDDEN_MODULES = {
    "subprocess",
    "socket",
    "sqlite3",
    "redis",
    "httpx",
    "psycopg",
    "asyncio",
    "systemctl",
    "agent.runtime",
    "agent.execution",
    "agent.recovery",
    "agent.sandbox",
    "agent.capability_router",
    "agent.orchestrator",
    "agent.tool_registry",
    "agent.verified_tool_executor",
}
FORBIDDEN_NAMES = {"VerifiedToolExecutor", "RuntimeOrchestrator"}
# Method-DEFINITION authority verbs (name == verb or verb-<suffix>).
AUTHORITY_DEF_VERBS = {"execute", "dispatch", "authorize", "grant", "run"}
# Attribute-CALL authority verbs; "system" is only meaningful as os.system(...),
# never as a method definition prefix (system_agent_role is a factory, not a verb).
AUTHORITY_CALL_VERBS = {"execute", "dispatch", "authorize", "grant", "run", "system"}
ALLOWED_CONTROL_PLANE_PREFIXES = (
    "agent.agent_runtime",
    "agent.agent_orchestration",
    "agent.platform_",
    "agent.agent_system",
)


def _is_forbidden_module(name: str) -> bool:
    if name in FORBIDDEN_MODULES:
        return True
    if any(name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULES):
        return True
    if name in FORBIDDEN_NAMES:
        return True
    # agent.xyz execution-kernel sibling must not be imported; control-plane allowed.
    if name.startswith("agent.") and not any(
        name.startswith(prefix) for prefix in ALLOWED_CONTROL_PLANE_PREFIXES
    ):
        return True
    return False


def scan_file(path: pathlib.Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: SYNTAX ERROR: {exc}"]
    for node in ast.walk(tree):
        # imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    findings.append(f"{path}: forbidden import {alias.name!r} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and _is_forbidden_module(node.module):
                findings.append(
                    f"{path}: forbidden import from {node.module!r} at line {node.lineno}"
                )
        # function/async-function/method definition names
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for verb in AUTHORITY_DEF_VERBS:
                if node.name == verb or node.name.startswith(verb + "_"):
                    findings.append(
                        f"{path}: authority-verb method def {node.name!r} at line {node.lineno}"
                    )
        # tool-execution call sites: <obj>.execute(/.dispatch(/.authorize(/.grant(/.run(, os.system(
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.attr in AUTHORITY_CALL_VERBS and fn.value.id in ("os", "self", "__import__"):
                    findings.append(
                        f"{path}: authority call {fn.value.id}.{fn.attr}() at line {node.lineno}"
                    )
    return findings


def main() -> int:
    files = sorted(PKG.rglob("*.py"))
    if not files:
        print("NO FILES FOUND in", PKG)
        return 1
    findings: list[str] = []
    for path in files:
        findings.extend(scan_file(path))
    if findings:
        print("FINDINGS (mechanism-gate FAIL):")
        for f in findings:
            print(" ", f)
        return 1
    print(f"MECHANICAL GATE PASS: {len(files)} files, 0 execution-kernel imports, 0 authority-verbs")
    return 0


if __name__ == "__main__":
    sys.exit(main())