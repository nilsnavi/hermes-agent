"""Provider Registry CLI — safe status output (Sprint 0.4).

Usage (from repo root, with the Hermes venv):

    python -m agent.provider_registry.cli status
    python -m agent.provider_registry.cli status --probe
    python -m agent.provider_registry.cli status --json
    python -m agent.provider_registry.cli status --diagnostics
    python -m agent.provider_registry.cli feature

No credential values anywhere in normal status. --diagnostics appends a
one-way sha256[:10] fingerprint per provider (identity only, not
reversible).

The CLI is a read-only debug tool: it builds an isolated registry from the
current config/env in memory and never touches production routing,
config, auth.json or cron jobs. It works with the feature flag off —
nothing in Hermes imports this package at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from typing import Any, Dict, List

from . import ProviderRegistry, flag_enabled
from .bootstrap import _credential_for, _custom_providers, build_registry, load_config, load_env

COLUMNS = [
    ("id", "Provider", 14),
    ("healthStatus", "Health", 11),
    ("authStatus", "Auth", 10),
    ("routingEligible", "Routing", 8),
    ("circuitState", "Circuit", 10),
    ("defaultModel", "Default model", 30),
    ("availabilityReason", "Reason", 18),
    ("fallbackPriority", "FB prio", 8),
    ("lastHttpStatus", "Last HTTP", 9),
    ("lastErrorCode", "Last error", 18),
]

# canonical display order for the baseline table
_ROW_ORDER = {
    "opencode": 0, "deepseek": 1, "openrouter": 2, "openai-api": 3,
    "anthropic": 4, "google": 5, "huggingface": 6, "github-copilot": 7,
    "nous": 8, "claudehub": 9, "codex.sale": 10, "agentrouter": 11,
}


def _masked_fp(provider_id: str, env: Dict[str, str], config: Dict[str, Any]) -> str:
    """sha256[:10] fingerprint of the credential — one-way, diagnostics only."""
    value = _credential_for(provider_id, env, config, _custom_providers(config))
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def _build_statuses(args: argparse.Namespace) -> List[Dict[str, Any]]:
    config = load_config()
    env = load_env()
    creds: Dict[str, str] = {}
    reg = ProviderRegistry()
    build_registry(reg, config=config, env=env, credentials_out=creds)
    if args.probe:
        from .health import HealthChecker

        checker = HealthChecker(reg, env=env, credentials=creds)
        checker.run_probe_batch()
    rows = reg.get_provider_statuses()
    rows.sort(key=lambda r: _ROW_ORDER.get(r["id"], 99))
    if args.diagnostics:
        for r in rows:
            r["_fp"] = _masked_fp(r["id"], env, config)
    return rows


def _print_table(rows: List[Dict[str, Any]], with_fp: bool) -> None:
    headers = [c[1] for c in COLUMNS]
    widths = [c[2] for c in COLUMNS]
    if with_fp:
        headers.append("Key fp")
        widths.append(12)
    line = " ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        cells = []
        for col, w in zip(COLUMNS, widths):
            if col[0] == "routingEligible":
                v = "YES" if r.get("routingEligible") else "no"
            elif col[0] == "circuitState":
                v = r.get("circuitState", "?")
            else:
                v = str(r.get(col[0], ""))
            cells.append(v.ljust(w)[:w])
        if with_fp:
            fp = r.get("_fp", "") or "-" * 10
            cells.append(fp.ljust(12))
        print(" ".join(cells))


def _fallback_line(config: Dict[str, Any], env: Dict[str, str]) -> str:
    reg = ProviderRegistry()
    build_registry(reg, config=config, env=env)
    cands = reg.get_fallback_candidates()
    if not cands:
        return "NONE (all broken/unavailable)"
    return ", ".join(f"{c['id']}(prio {c['fallbackPriority']})" for c in cands)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="provider_registry", description="Hermes Provider Registry V1 status")
    sub = ap.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="registry table")
    p_status.add_argument("--probe", action="store_true", help="run low-cost live probes first")
    p_status.add_argument("--json", action="store_true", help="machine-readable output")
    p_status.add_argument("--diagnostics", action="store_true",
                          help="append masked key fingerprints (one-way sha256[:10])")
    sub.add_parser("feature", help="feature flag state")
    args = ap.parse_args(argv)

    if args.cmd == "feature":
        print(f"HERMES_PROVIDER_REGISTRY_V2={'true' if flag_enabled() else 'false'}")
        return 0

    if args.cmd != "status":
        ap.print_help()
        return 2

    rows = _build_statuses(args)
    if args.json:
        out = [
            {
                "provider": r["id"],
                "health": r["healthStatus"],
                "auth": r["authStatus"],
                "routing": r["routingEligible"],
                "circuit": r["circuitState"],
                "model": r["defaultModel"],
                "reason": r["availabilityReason"],
                "lastHttp": r.get("lastHttpStatus"),
                "lastError": r.get("lastErrorCode"),
            }
            for r in rows
        ]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print("=== Hermes Provider Registry V1 — status ===")
    if not flag_enabled():
        print("NOTE: HERMES_PROVIDER_REGISTRY_V2 not set (production flag=false) — "
              "registry inactive at runtime; this is a read-only snapshot.")
    _print_table(rows, args.diagnostics)
    config = load_config()
    env = load_env()
    print(f"\nFallback candidates: {_fallback_line(config, env)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())