# Provider routing and fallback contract

## Purpose and baseline
Изолированный core делает детерминированный route plan; production runtime остаётся authoritative.

## Production runtime observations
Проверены `hermes_core/application/provider_router.py`, `hermes_core/ports/providers.py`, `hermes_core/domain/routing.py`, `agent/model_resolution.py`, `agent/turn_model.py`, `gateway/session.py`. Provider resolution ownership VERIFIED; production precedence, pools, recovery and cache affinity PARTIAL/UNVERIFIED.

## Routing boundary
Core contains immutable values only; adapters own clients, credentials and health.

## Route purpose and request
`RoutePurpose` preserves existing MAIN/COMPRESSION/VISION/TITLE/SEARCH. Request context is passed to runtime port; no secrets or mutable clients.

## Candidate and route decision
`RouteCandidate` validates non-empty provider/model, non-negative integer precedence and one purpose. Credential reference is opaque. Existing immutable `RouteDecision` remains C4-compatible.

## Deterministic precedence
`RoutePlan` sorts precedence then provider/model/reference; ties are stable. Duplicate logical identity and mixed-purpose plans fail closed.

## Fallback semantics
`FallbackPolicy` is an immutable policy supplied with the plan; its default is deny-all. Only an explicitly validated policy may allow a classification. Evidence must name the exact in-plan candidate. Progression is strictly forward (A→B→C), never backward or cyclic. Empty selection returns `NO_ROUTE`; no remaining legal candidate returns `EXHAUSTED`.

## Retry versus fallback
RoutePlan never retries, sleeps or backs off. Retry belongs runtime orchestration.

## Credential ownership and recovery
Only opaque references cross the boundary. Credential storage, rotation, cooldown and recovery are adapter-owned and UNVERIFIED here.

## Failure classification
Provider-neutral classes include transient, rate limited, credential unavailable, authentication, model unavailable, invalid request, provider internal and unknown; no SDK exceptions or raw responses enter core.

## Candidate exhaustion
Terminal statuses are explicit `NO_ROUTE`, `EXHAUSTED` and `FALLBACK_NOT_ALLOWED`.

## Prompt-cache implications
Cache-safe fallback/affinity is UNVERIFIED; no cache is implemented.

## Session/profile scope
Profile/session precedence and home-provider affinity remain runtime mapping gaps.

## Adapter responsibilities
Adapters translate provider outcomes, select credentials and persist health without exposing secrets.

## Known gaps and migration implications
B5 is `PARTIALLY_ADDRESSED`; real adapter validation, runtime precedence and recovery evidence remain required. Production migration is NO-GO.
