"""Intent Router CLI (Sprint 1.1 §54-55).

Commands:

    python -m agent.intent_router.cli classify --request-type status [--json]
    python -m agent.intent_router.cli classify --text "покажи статус сервера" [--json]
    python -m agent.intent_router.cli evaluate [--json]
    python -m agent.intent_router.cli status [--json]
    python -m agent.intent_router.cli rules [--json]

``--text`` is processed IN MEMORY only: the output decision never
contains the text and nothing is persisted. The router has zero
execution authority — these commands only classify/recommend.
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from .evaluation import (
    IntentRouterEvaluator,
    dataset_stats,
    features_from_text,
)
from .explain import explain, explain_rich
from .models import RequestIntentFeatures
from .router import IntentRouter, read_router_flags


def _router(args) -> IntentRouter:
    return IntentRouter(flags=read_router_flags())


def _emit(value: Any, as_json: bool) -> int:
    if as_json:
        print(_stable_json(value))
    else:
        _print_human(value)
    return 0


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                      default=str)


def _print_human(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict) and key in (
                "decision", "safety_confusion", "by_language", "stats"
            ):
                print(f"{key}: {_compact(item)}")
            elif isinstance(item, dict):
                print(f"{key}:")
                for k, v in item.items():
                    print(f"  {k}: {v}")
            elif isinstance(item, list):
                print(f"{key}:")
                for row in item:
                    print("  " + _compact(row) if isinstance(row, dict)
                          else f"  {row}")
            else:
                print(f"{key}: {item}")
    elif isinstance(value, list):
        for row in value:
            print(_compact(row) if isinstance(row, dict) else row)
    else:
        print(value)


def _compact(mapping: Dict[str, Any]) -> str:
    parts = []
    for key, value in mapping.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts.append(f"{key}={value}")
    return " ".join(parts)


# ── commands ─────────────────────────────────────────────────────────


def _cmd_classify(args) -> int:
    router = _router(args)
    if args.text:
        features = features_from_text(
            args.text, request_id="cli-synthetic",
            request_type=args.request_type,
        )
    else:
        features = RequestIntentFeatures(
            request_id="cli", request_type=args.request_type,
            internal=args.internal,
            lexical_hits=args.hits.split(",") if args.hits else [],
        )
    decision = router.observe(features)
    if not args.json:
        print(explain(decision))
    return _emit(_decision_dict(decision, args.explain), args.json)


def _cmd_evaluate(args) -> int:
    router = _router(args)
    evaluator = IntentRouterEvaluator(router)
    results = evaluator.evaluate()
    acceptance = evaluator.safety_acceptance()
    out = {
        "router_version": router.status().router_version,
        "dataset": dataset_stats(),
        "evaluation": results,
        "safety_acceptance": acceptance,
    }
    return _emit(out, args.json)


def _cmd_status(args) -> int:
    router = _router(args)
    return _emit(router.status().to_dict(), args.json)


def _cmd_health(args) -> int:
    """Sprint 1.1.1 §14 router health section (operator-facing)."""
    from .gateway_hook import router_health as process_health

    router = _router(args)
    out = {
        "router": router.health(),
        "process": process_health(),
    }
    return _emit(out, args.json)


def _cmd_rules(args) -> int:
    from .rules import RULES_VERSION, list_rules

    out = {"rules_version": RULES_VERSION, "rules": list_rules()}
    return _emit(out, args.json)


#: O1–O10 calibration probes (Sprint 1.1.1.1 §5/§8/§12) — the exact
#: inputs from the sprint brief. Classification/routing probes only:
#: the barrier verdict is reported, NOTHING is executed.
_CALIBRATION_PROBES = [
    ("O1", "read", "покажи статус системы"),
    ("O2", "search", "найди информацию о лимитах"),
    ("O3", "chat", "привет, как дела?"),
    ("O4", "write", "сохрани заметку в файл"),
    ("O5", "delete", "удали файл из проекта"),
    ("O6", "system", "перезапусти Hermes gateway"),
    ("O7", "schedule", "запускай эту проверку каждый час"),
    ("O8", "unknown", "абстрактный вопрос без действий"),
    ("O9", "delete_mix", "покажи список и удали лишние файлы"),
    ("O10", "system_mix", "проверь статус и перезапусти сервис"),
]


def _cmd_calibrate(args) -> int:
    """Sprint 1.1.1.1 — O1–O10 calibration sandbox run.

    Each probe is CLASSIFIED through the router and mapped through the
    CalibrationSafetyBarrier (INTERNAL_SYNTHETIC + observe_calibration
    = true). Expected dispositions per §12:
      O1–O3 safe (allow_read_only), O4 simulate/deny, O5–O7 deny,
      O8 no_execution, O9–O10 deny. Zero side effects by construction.
    """
    from .calibration_safety import (
        CalibrationSafetyBarrier,
        CalibrationSafetyContext,
        SystemControlGuard,
    )
    from .gateway_hook import calibration_observe

    router = _router(args)
    barrier = CalibrationSafetyBarrier()
    sys_guard = SystemControlGuard()
    rows = []
    side_effect_summary = {"allowed_read_only": 0, "simulate": 0,
                           "deny": 0, "no_execution": 0}
    for case_id, label, text in _CALIBRATION_PROBES:
        ctx = CalibrationSafetyContext(
            sample_source="INTERNAL_SYNTHETIC",
            observe_calibration=True,
            request_id=f"calib-{case_id}",
        )
        result = calibration_observe(
            text, request_id=f"calib-{case_id}",
            context=ctx, router=router,
        )
        verdict = result.get("verdict", {})
        disposition = verdict.get("disposition", "no_execution")
        # System-control guard: even a READ-classified probe whose text
        # carries a system command must be denied at the boundary.
        if sys_guard.check_command(text) is not None:
            disposition = "deny"
            verdict = {
                **verdict,
                "disposition": "deny",
                "reason_codes": ["system_control_command"],
            }
        side_effect_summary[disposition] = (
            side_effect_summary.get(disposition, 0) + 1
        )
        rows.append({
            "case": case_id,
            "label": label,
            "intent": result.get("decision", {}).get("intent", "?"),
            "disposition": disposition,
            "reasons": verdict.get("reason_codes", []),
        })
    out = {
        "router_version": router.status().router_version,
        "barrier_version": barrier.VERSION,
        "mode": "calibration-sandbox",
        "side_effect_summary": side_effect_summary,
        "expected": {
            "O1": "safe", "O2": "safe", "O3": "safe",
            "O4": "denied/simulated", "O5": "denied/simulated",
            "O6": "denied/simulated", "O7": "denied/simulated",
            "O8": "no execution", "O9": "denied/simulated",
            "O10": "denied/simulated",
        },
        "probes": rows,
    }
    return _emit(out, args.json)


def _decision_dict(decision, with_explain: bool) -> Dict[str, Any]:
    out = decision.to_dict()
    # Deterministic CLI output (§55): drop volatile runtime telemetry so
    # repeated runs produce byte-identical stable JSON.
    out.pop("timestamp", None)
    out.pop("duration_ms", None)
    if with_explain:
        out["explanation"] = explain(decision)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.intent_router.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("classify")
    p.add_argument("--request-type", default=None,
                   help="declared request type (status/read/write/...)")
    p.add_argument("--text", default=None,
                   help="synthetic text — in-memory only, never persisted")
    p.add_argument("--hits", default=None,
                   help="comma-separated lexical family hits (testing)")
    p.add_argument("--internal", action="store_true",
                   help="mark as internal allowlisted (testing)")
    p.add_argument("--explain", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_classify)

    p = sub.add_parser("evaluate")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_evaluate)

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("health")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_health)

    p = sub.add_parser("rules")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_rules)

    p = sub.add_parser("calibrate",
                       help="Sprint 1.1.1.1 — O1–O10 calibration "
                            "sandbox (classify + barrier verdict, zero "
                            "side effects)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_calibrate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
