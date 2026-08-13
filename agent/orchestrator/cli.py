"""Safe orchestrator CLI (Sprint 1.0.5) — fake tools only, no connectors.

Usage:
    python -m agent.orchestrator.cli run-demo [--steps N]
    python -m agent.orchestrator.cli inspect <run_id> [--db PATH]
    python -m agent.orchestrator.cli resume <run_id> --dry-run [--db PATH]

run-demo uses a throwaway temp SQLite DB; inspect/resume read a DB you
point at. Nothing here touches the production gateway or state.db.
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry
from agent.persistence import SQLiteExecutionStore
from agent.runtime.context import TaskContext

from .orchestrator import RuntimeOrchestrator
from .policy import ExecutionPolicy


def _demo_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("search", lambda a, c: {"hits": 3},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("fetch", lambda a, c: {"rows": 10},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("save_draft", lambda a, c: {"draft_id": "d-1"},
                 metadata=ToolMetadata(idempotent=False,
                                       side_effect_class=SideEffectClass.REVERSIBLE_WRITE))
    return reg


def _demo_steps(n: int):
    tools = ["search", "fetch", "save_draft"]
    return [{"name": f"step-{i}", "tool": tools[i % len(tools)]} for i in range(n)]


def _print_result(result) -> None:
    print(f"run_id      : {result.run_id}")
    print(f"status      : {result.status}")
    print(f"stop_reason : {result.stop_reason.value if result.stop_reason else None}")
    print(f"steps       : {result.steps_executed}")
    print(f"tool_calls  : {result.tool_calls}")
    print(f"approvals   : {result.approvals}")
    print(f"replans     : {result.replans}")
    print(f"failures    : {result.failures}")
    print(f"disposition : {result.disposition}")
    if result.error:
        print(f"error       : {result.error}")


def _cmd_run_demo(args) -> int:
    db = tempfile.mkdtemp(prefix="orchestrator-demo-")
    path = os.path.join(db, "demo.db")
    store = SQLiteExecutionStore(path)
    orchestrator = RuntimeOrchestrator(store, _demo_registry())
    context = TaskContext(
        goal="demo run",
        allowed_tools=["search", "fetch", "save_draft"],
        metadata={"task_type": "demo"},
    )
    result = orchestrator.run(context, policy=ExecutionPolicy(), step_specs=_demo_steps(args.steps))
    _print_result(result)
    print(f"db          : {path}")
    store.close()
    return 0


def _cmd_inspect(args) -> int:
    store = SQLiteExecutionStore(args.db)
    orchestrator = RuntimeOrchestrator(store, _demo_registry())
    result = orchestrator.inspect(args.run_id)
    _print_result(result)
    store.close()
    return 0


def _cmd_resume_dry_run(args) -> int:
    store = SQLiteExecutionStore(args.db)
    orchestrator = RuntimeOrchestrator(store, _demo_registry())
    result = orchestrator.resume(args.run_id)  # report-only: no engine → no tools
    _print_result(result)
    store.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.orchestrator.cli",
                                     description="Safe orchestrator CLI (fake tools)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run-demo", help="run a fake 3-step demo")
    p_run.add_argument("--steps", type=int, default=3)
    p_run.set_defaults(func=_cmd_run_demo)

    p_inspect = sub.add_parser("inspect", help="read-only run inspection")
    p_inspect.add_argument("run_id")
    p_inspect.add_argument("--db", required=True, help="SQLite DB path")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_resume = sub.add_parser("resume", help="resume (dry-run report only)")
    p_resume.add_argument("run_id")
    p_resume.add_argument("--dry-run", action="store_true", default=True)
    p_resume.add_argument("--db", required=True, help="SQLite DB path")
    p_resume.set_defaults(func=_cmd_resume_dry_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
