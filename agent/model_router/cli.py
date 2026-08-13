"""Model Router CLI diagnostics (Sprint 0.5 §24) — no secrets, no network.

Usage:
    python -m agent.model_router.cli profiles
    python -m agent.model_router.cli route --profile BALANCED [--intent ...]
    python -m agent.model_router.cli route --profile CODING --why
    python -m agent.model_router.cli flags
"""

from __future__ import annotations

import argparse
import os
import sys

from agent.provider_registry import ProviderRegistry

from . import (
    all_models,
    all_profiles,
    get_profile,
    get_router,
    router_v2_enabled,
    shadow_enabled,
)
from .router import ModelRouter

DEFAULT_SHADOW_PROFILE = "BALANCED"


def _registry() -> ProviderRegistry:
    """Providers from live config (no network, no probes) when available."""
    try:
        from agent.provider_registry.bootstrap import build_registry

        reg = ProviderRegistry()
        build_registry(reg)
        return reg
    except Exception:
        return ProviderRegistry()


def cmd_profiles(profile_filter: str = "") -> int:
    print(f"{'Profile':<12} {'Enabled':<8} {'Required caps':<28} {'Preferred caps':<32} {'Fallback':<12} Providers")
    for p in all_profiles():
        if profile_filter and p.id != profile_filter.upper():
            continue
        print(f"{p.id:<12} {str(p.enabled):<8} {','.join(p.requiredCapabilities or ['-']):<28} "
              f"{','.join(p.preferredCapabilities or ['-']):<32} {(p.fallbackProfile or '-'):<12} "
              f"{','.join(p.preferredProviders or ['-'])}")
    return 0


def cmd_route(args) -> int:
    profile = args.profile.upper()
    router = get_router(_registry())
    try:
        d = router.route_model(
            profile=profile,
            intent=args.intent or "",
            excludedProviders=args.excluded.split(",") if args.excluded else None,
            explicit=(args.explicit.split("/") if args.explicit and "/" in args.explicit else None),
        )
    except ValueError as e:
        print(f"PROFILE ERROR: {e}")
        return 2
    print(f"profile      : {d.profile}")
    print(f"route        : {d.provider}/{d.model}" if d.ok else f"route        : —")
    print(f"reasonCode   : {d.reasonCode}")
    print(f"reason       : {d.reason}")
    print(f"eligible     : {d.routingEligible}")
    print(f"capabilities : {','.join(d.capabilityMatch) or '-'}")
    print(f"cost/latency : {d.costClass}/{d.latencyClass}")
    print("fallback     :")
    for c in d.fallbackCandidates:
        print(f"  - {c.provider}/{c.model} ({c.reason})")
    if d.rejected:
        print("rejected     :")
        for r in d.rejected:
            print(f"  - {r}")
    return 0


def cmd_route_explicit(args) -> int:
    """Test explicit override handling (§17/§28): session/admin picks a model."""
    router = get_router(_registry())
    p_provider = args.provider.strip()
    p_model = args.model.strip()
    d = router.route_model(profile=args.profile.upper(),
                           explicit=(p_provider, p_model))
    print(f"profile      : {args.profile.upper()}")
    print(f"requested    : {p_provider}/{p_model}")
    print(f"result       : {d.reasonCode}")
    print(f"route        : {d.provider}/{d.model}")
    print(f"reason       : {d.reason}")
    print("fallback:")
    for c in d.fallbackCandidates:
        print(f"  - {c.provider}/{c.model} ({c.reason})")
    return 0


def cmd_shadow(args) -> int:
    """Shadow comparison of legacy runtime choice vs router choice."""
    reg = _registry()
    legacy = (args.legacy or "").strip()
    if "/" not in legacy:
        print("usage: python -m agent.model_router.cli shadow-status "
              "--legacy provider/model [--profile BALANCED]")
        return 2
    legacy_provider, legacy_model = legacy.split("/", 1)
    profile = (args.profile or DEFAULT_SHADOW_PROFILE).upper()
    from agent.model_router.shadow import shadow_compare

    d = shadow_compare(router=get_router(reg), legacy_provider=legacy_provider,
                       legacy_model=legacy_model, profile=profile)
    print(f"profile       : {profile}")
    print(f"legacy        : {legacy_provider}/{legacy_model}")
    print(f"router        : {d.provider}/{d.model}")
    print(f"same          : {d.provider == legacy_provider and d.model == legacy_model}")
    print(f"reasonCode    : {d.reasonCode}")
    print(f"shadow_enabled: {shadow_enabled()}")
    return 0


def cmd_flags() -> int:
    print(f"HERMES_PROVIDER_REGISTRY_V2 = {os.environ.get('HERMES_PROVIDER_REGISTRY_V2', 'false')}")
    print(f"HERMES_MODEL_ROUTER_V2        = {os.environ.get('HERMES_MODEL_ROUTER_V2', 'false')}")
    print(f"HERMES_MODEL_ROUTER_SHADOW    = {os.environ.get('HERMES_MODEL_ROUTER_SHADOW', 'false')}")
    print(f"router_v2_enabled()           = {router_v2_enabled()}")
    print(f"shadow_enabled()              = {shadow_enabled()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model_router.cli",
                                     description="Model Router V1 diagnostics (shadow, no side effects)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_profiles = sub.add_parser("profiles", help="list logical model profiles")
    p_profiles.add_argument("--profile", default="", help="filter by profile id")

    p_route = sub.add_parser("route", help="show what profile resolves to (shadow)")
    p_route.add_argument("--profile", default="BALANCED")
    p_route.add_argument("--intent", default="")
    p_route.add_argument("--excluded", default="")
    p_route.add_argument("--explicit", default="", help="provider/model override to test")

    p_explicit = sub.add_parser("explicit", help="test explicit provider/model override (MODEL_UNSUPPORTED handling)")
    p_explicit.add_argument("--provider", required=True)
    p_explicit.add_argument("--model", required=True)
    p_explicit.add_argument("--profile", default="BALANCED")

    p_shadow = sub.add_parser("shadow-status",
                              help="compare legacy runtime choice vs router choice")

    p_shadow.add_argument("--legacy", default="", help="legacy 'provider/model'")
    p_shadow.add_argument("--profile", default="BALANCED")

    sub.add_parser("flags", help="show feature flags")

    args = parser.parse_args(argv)
    if args.command == "profiles":
        cmd_profiles(args.profile)
    elif args.command == "route":
        return cmd_route(args)
    elif args.command == "explicit":
        return cmd_route_explicit(args)
    elif args.command == "shadow-status":
        return cmd_shadow(args)
    else:
        return cmd_flags()
    return 0


if __name__ == "__main__":
    sys.exit(main())