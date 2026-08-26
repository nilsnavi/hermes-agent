#!/usr/bin/env python3
"""Mechanical AST gate for Phase 8.3 isolated shadow worker (Phase 8.3 §28).

Proves, over ``agent/shadow_worker``:

  UNAUTHORIZED_EXECUTION_PATHS        = 0  (subprocess, os.system, shell=True,
       systemctl, kill, signal, eval, exec, pickle/marshal, redis/db/network
       clients, gateway/executor/adapter imports, open-with-write, filesystem
       mutation outside the worker).
  WORKER_TO_PRODUCTION_CHANNELS       = 0  (no reply/respond/override/apply/
       promote/retry_production/send_to_gateway surface -> no return path).
  GATEWAY_RUNTIME_COUPLING            = 0  (no import of the gateway, its
       adapters, executors, intent_router, or the production request/response).

This mirrors the established ``scan_shadow_runtime.py`` gate and the hermetic
principle: the worker must contain zero authority and zero coupling to the live
production gateway.
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO / "agent" / "shadow_worker"

# -- imports that grant execution / network / service / persistence / gateway --
FORBIDDEN_IMPORTS = {
    "subprocess", "asyncio", "systemctl", "signal", "importlib", "pickle",
    "marshal", "dill", "cloudpickle", "shelve",
    "redis", "httpx", "requests", "psycopg", "psycopg2", "sqlalchemy",
    "aiohttp", "websockets", "smtplib", "urllib.request",
    "agent.execution", "agent.recovery", "agent.sandbox", "agent.scheduler",
    "agent.provider_config", "agent.orchestrator", "agent.gateway", "agent.response",
    "agent.executor", "agent.verified_tool_executor", "agent.capability_router",
    "agent.gateway_v2", "agent.intent_router", "agent.cloud_gateway",
    "agent.execution_authority",
}
# Modules the worker may reuse (the read-only control-plane vertical only).
ALLOWED_CONTROL_PLANE_PREFIXES = (
    "agent.platform_shadow", "agent.agent_integration", "agent.agent_system",
    "agent.agent_runtime", "agent.platform_memory", "agent.platform_policy",
    "agent.agent_security_boundary",
)

# -- raw execution / I/O / service primitives (call sites) --
EXEC_CALL_NAMES = {"eval", "exec", "__import__", "systemctl", "kill", "Popen",
                   "send_signal", "check_output", "call"}
OS_EXEC_ATTRS = {"system", "popen", "run", "call", "Popen", "kill",
                 "send_signal", "check_output", "systemctl"}
# -- filesystem mutation surfaces (write/delete/create dirs) --
FS_WRITE_ATTRS = {"remove", "rmdir", "makedirs", "mkdir", "rename"}
CHANNEL_ATTRS = {"reply", "respond", "override", "apply", "promote",
                 "retry_production", "send_to_gateway", "force_production"}

F1_exec, F2_fs, F3_channel, F4_coupling = [], [], [], []


def _is_forbidden_import(name: str) -> bool:
    if name in FORBIDDEN_IMPORTS:
        return True
    if name.startswith("agent.") and any(name.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
        return True
    return False


def _couples_gateway(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in (
        "gateway", "agent.gateway", "agent.gateway_v2", "agent.intent_router",
        "agent.cloud_gateway", "agent.response", "agent.executor",
    ))


def visit(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = str(path.relative_to(REPO))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    F1_exec.append((module, f"import {alias.name}", node.lineno))
                if _couples_gateway(alias.name):
                    F4_coupling.append((module, f"import {alias.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if _is_forbidden_import(base):
                F1_exec.append((module, f"from {base} import ...", node.lineno))
            if _couples_gateway(base):
                F4_coupling.append((module, f"from {base} import ...", node.lineno))
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if _is_forbidden_import(full):
                    F1_exec.append((module, f"from {full}", node.lineno))
                if _couples_gateway(full):
                    F4_coupling.append((module, f"from {full}", node.lineno))

        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in EXEC_CALL_NAMES:
                F1_exec.append((module, f"{fn.id}( ... )", node.lineno))
            if isinstance(fn, ast.Attribute):
                if isinstance(fn.value, ast.Name) and fn.value.id in ("os", "subprocess"):
                    if fn.attr in OS_EXEC_ATTRS:
                        F1_exec.append((module, f"{fn.value.id}.{fn.attr}( ... )", node.lineno))
                # direct production-response mutation pattern: .apply(...) / .override(...)
                if fn.attr in CHANNEL_ATTRS and not (
                        isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls")):
                    F3_channel.append((module, f"callable channel {ast.dump(fn)}", node.lineno))
                if isinstance(fn.value, ast.Name) and fn.value.id == "os" and fn.attr in FS_WRITE_ATTRS:
                    F2_fs.append((module, f"os.{fn.attr}( ... ) filesystem mutation", node.lineno))
            for kw in node.keywords:
                if kw.arg == "shell":
                    F1_exec.append((module, f"shell={ast.dump(kw.value)}", node.lineno))
            if isinstance(fn, ast.Name) and fn.id == "open":
                args = [a for a in node.args] + [k.value for k in node.keywords if k.arg == "mode"]
                if any(isinstance(a, ast.Constant) and isinstance(a.value, str)
                       and ("w" in a.value or "a" in a.value or "+" in a.value) for a in args):
                    F2_fs.append((module, "open(..., 'w'/'a'/'+') filesystem write", node.lineno))

        # member ACCESS of a forbidden production channel (non-call).
        if isinstance(node, ast.Attribute) and node.attr in CHANNEL_ATTRS and not (
                isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")):
            F3_channel.append((module, f"channel member read {node.attr}", node.lineno))


def main() -> int:
    files = 0
    for f in sorted(TARGET.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        files += 1
        try:
            visit(f)
        except SyntaxError as exc:
            print(f"SYNTAX ERROR {f}: {exc}")
            return 2

    print(f"Scanned {files} file(s) in {TARGET}.")
    for label, group in (("UNAUTHORIZED_EXECUTION_PATHS", F1_exec),
                         ("WORKER_TO_PRODUCTION_CHANNELS", F3_channel),
                         ("GATEWAY_RUNTIME_COUPLING", F4_coupling),
                         ("FILESYSTEM_MUTATION_OUTSIDE_WORKER", F2_fs)):
        print(f"{label}={len(group)}")
        for module, kind, line in group:
            print(f"    {module}:{line} {kind}")

    total = len(F1_exec) + len(F2_fs) + len(F3_channel) + len(F4_coupling)
    if total:
        print("GATE FAIL")
        return 1
    print("GATE PASS: UNAUTHORIZED_EXECUTION_PATHS=0 WORKER_TO_PRODUCTION_CHANNELS=0 "
          "GATEWAY_RUNTIME_COUPLING=0 FILESYSTEM_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())