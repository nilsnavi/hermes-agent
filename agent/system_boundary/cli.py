"""SBL CLI (Sprint 1.3.3 §67-§68).

Read-only commands only in 1.3.3: status / inspect / inspect-path /
inspect-command / graph / deps / refresh. NO execute / apply /
repair / restart / rollback / write / delete.
"""

from typing import Any, Dict

from . import effective_action as ea
from . import path_resolver as pr
from .boundary import SystemBoundaryLayer, SBL_VERSION
from .service_graph import ServiceGraph


def _default_sbl() -> SystemBoundaryLayer:
    return SystemBoundaryLayer(mode="shadow")


def status() -> Dict[str, Any]:
    """hermes sbl status — mode + version (read-only)."""
    sbl = _default_sbl()
    return {
        "boundary_version": SBL_VERSION,
        "mode": sbl.mode,
        "graph": (sbl.graph.health if sbl.graph else "UNAVAILABLE"),
    }


def inspect_path(path: str) -> Dict[str, Any]:
    """hermes sbl inspect-path — classification only, no writes."""
    sbl = _default_sbl()
    resolved = pr.resolve_path(path)
    decision = sbl.authorize_path(path)
    return {
        "path": path,
        "resolved": resolved.resolved,
        "resource_class": resolved.resource_class.value,
        "operation_class": decision.operation_class,
        "effective_action_class": decision.effective_action_class,
        "blast_radius": decision.blast_radius,
        "risk_floor": decision.risk_floor,
        "verdict": decision.verdict,
        "reason_code": decision.reason_code,
        "wrote": False,
    }


def inspect_command(command: str) -> Dict[str, Any]:
    """hermes sbl inspect-command — classification only, NEVER
    executes the command (§67)."""
    sbl = _default_sbl()
    decision = sbl.authorize_command(command)
    return {
        "command": command,
        "verdict": decision.verdict,
        "reason_code": decision.reason_code,
        "operation_class": decision.operation_class,
        "effective_action_class": decision.effective_action_class,
        "blast_radius": decision.blast_radius,
        "executed": False,
    }


def graph() -> Dict[str, Any]:
    """hermes sbl graph — current graph summary (read-only)."""
    sbl = _default_sbl()
    g = sbl.graph
    if g is None:
        return {"health": "UNAVAILABLE", "nodes": 0, "edges": 0,
                "graph_version": None}
    return {
        "health": g.health,
        "nodes": g.node_count(),
        "edges": g.edge_count(),
        "graph_version": g.graph_version,
    }


def deps(target: str) -> Dict[str, Any]:
    """hermes sbl deps <target> — dependency query (read-only)."""
    sbl = _default_sbl()
    g = sbl.graph
    if g is None or not g.has_node(target):
        return {"target": target, "dependencies": [],
                "known": False, "health": g.health if g else "UNAVAILABLE"}
    return {
        "target": target,
        "dependencies": g.dependencies(target),
        "known": True,
        "health": g.health,
    }


def refresh() -> Dict[str, Any]:
    """hermes sbl refresh — bounded graph refresh (read-only sources;
    no mutation in 1.3.3; returns a PARTIAL placeholder graph)."""
    g = ServiceGraph(health="PARTIAL", graph_version="g-refresh-1.3.3")
    return {
        "health": g.health,
        "graph_version": g.graph_version,
        "nodes": g.node_count(),
        "edges": g.edge_count(),
        "note": "bounded discovery sources only; 1.3.3 placeholder",
    }


#: allowed CLI commands (§68) — explicit deny-list test target
CLI_COMMANDS = {
    "status": status,
    "inspect": inspect_path,
    "inspect-path": inspect_path,
    "inspect-command": inspect_command,
    "graph": graph,
    "deps": deps,
    "refresh": refresh,
}


def main(argv=None) -> int:
    """``python -m agent.system_boundary.cli`` — read-only SBL CLI.

    Sprint 1.3.3 allows ONLY: status / inspect-path / inspect-command
    / graph / deps / refresh. execute/apply/repair/restart/rollback/
    write/delete are NOT wired in 1.3.3 (§68).
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="agent.system_boundary.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=lambda a: status())

    p = sub.add_parser("inspect-path")
    p.add_argument("path")
    p.set_defaults(func=lambda a: inspect_path(a.path))

    p = sub.add_parser("inspect-command")
    p.add_argument("command")
    p.set_defaults(func=lambda a: inspect_command(a.command))

    p = sub.add_parser("graph")
    p.set_defaults(func=lambda a: graph())

    p = sub.add_parser("deps")
    p.add_argument("target")
    p.set_defaults(func=lambda a: deps(a.target))

    p = sub.add_parser("refresh")
    p.set_defaults(func=lambda a: refresh())

    # argparse with subparsers: add --json to the top-level parser
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    out = args.func(args)
    if getattr(args, "json", False):
        print(_json.dumps(out, ensure_ascii=False, indent=2,
                          default=str))
    else:
        for k, v in out.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "status",
    "inspect_path",
    "inspect_command",
    "graph",
    "deps",
    "refresh",
    "CLI_COMMANDS",
]
