"""Gateway V2 adapter (Sprint 1.0.6) — the safe bridge.

Sits ABOVE transport, BELOW request dispatch. With all flags false (the
production default) ``decide()`` returns LEGACY in microseconds and opens
nothing — 100% legacy behavior.

Fallback invariant (§9/§30): legacy fallback is allowed ONLY before any
V2 side effect (no AgentRun → always safe; run exists but ZERO
TOOL_STARTED → safe, mark cancelled). Once TOOL_STARTED exists,
fallback is FORBIDDEN — silently re-running through legacy could
DUPLICATE the external action → MANUAL_REVIEW / ERROR instead.
"""

from enum import Enum
from typing import Any, Dict, Optional

from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.execution.registry import ToolRegistry
from agent.orchestrator import ExecutionPolicy, RuntimeOrchestrator

from .canary import SafeCanaryToolRegistry, V2CanaryPolicy, default_canary_registry
from .context_builder import GatewayRequest, GatewayTaskContextBuilder
from .events import (
    CANARY_COMPLETED,
    CANARY_FAILED,
    CANARY_STARTED,
    DECISION,
    FALLBACK_LEGACY,
    SHADOW_FAILED,
    V2Telemetry,
)
from .flags import FeatureFlags, read_flags
from .result_mapper import V2ResultMapper
from .shadow import ShadowRunner, default_shadow_registry
from .shadow_policy import V2ShadowPolicy
from .store_factory import RuntimeV2StoreFactory


class V2Decision(Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    V2_CANARY = "v2_canary"


class GatewayV2Adapter:
    """Deterministic router + shadow + canary runner. Default: LEGACY."""

    def __init__(
        self,
        flags: Optional[FeatureFlags] = None,
        registry: Optional[ToolRegistry] = None,
        canary_policy: Optional[V2CanaryPolicy] = None,
        shadow_policy: Optional[V2ShadowPolicy] = None,
        store_factory: Optional[RuntimeV2StoreFactory] = None,
        clock=None,
    ) -> None:
        self._flags = flags or read_flags()
        self._registry = registry
        self._policy = canary_policy or V2CanaryPolicy(registry=registry)
        self._shadow_policy = shadow_policy or V2ShadowPolicy()
        self._factory = store_factory or RuntimeV2StoreFactory(self._flags)
        self._clock = clock
        self._telemetry = V2Telemetry()
        self._builder = GatewayTaskContextBuilder()
        self._mapper = V2ResultMapper()

    # ── routing ─────────────────────────────────────────────────────

    def decide(self, request: GatewayRequest) -> V2Decision:
        """Pure, fast, side-effect-free. All-false → LEGACY."""
        if not self._flags.enabled:
            self._telemetry.record(DECISION, request_id=request.request_id,
                                   mode="legacy", eligible=False,
                                   reason="v2_disabled")
            return V2Decision.LEGACY
        if self._flags.canary:
            eligible, reason = self._policy.is_eligible(request)
            if eligible:
                self._telemetry.record(DECISION, request_id=request.request_id,
                                       mode="v2_canary", eligible=True,
                                       reason="eligible")
                return V2Decision.V2_CANARY
            # not canary-eligible → fall through to the shadow check
            # (§20 precedence: CANARY > SHADOW > LEGACY)
            canary_reason = reason
        else:
            canary_reason = None
        if self._flags.shadow:
            eligible, reason = self._shadow_policy.is_eligible(request)
            if eligible:
                self._telemetry.record(DECISION, request_id=request.request_id,
                                       mode="shadow", eligible=True,
                                       reason="eligible")
                return V2Decision.SHADOW
            self._telemetry.record(DECISION, request_id=request.request_id,
                                   mode="legacy", eligible=False,
                                   reason=reason or canary_reason)
            return V2Decision.LEGACY
        self._telemetry.record(DECISION, request_id=request.request_id,
                               mode="legacy", eligible=False,
                               reason=canary_reason or "no_v2_mode")
        return V2Decision.LEGACY

    def decide_event(self, event: Any) -> V2Decision:
        """Defensive gateway-event shim: never raises, never opens stores."""
        try:
            request = self._request_from_event(event)
            return self.decide(request)
        except Exception:
            return V2Decision.LEGACY  # fail-open BEFORE any V2 side effect

    @staticmethod
    def _request_from_event(event: Any) -> GatewayRequest:
        request_id = getattr(event, "id", None) or "evt-unknown"
        user_id = getattr(event, "user_id", "") or ""
        session_id = getattr(event, "session_id", "") or ""
        text = getattr(event, "text", None)
        raw_metadata = getattr(event, "metadata", None)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        return GatewayRequest(
            request_id=str(request_id),
            user_id=str(user_id),
            session_id=str(session_id),
            goal=str(text or "")[:500],
            metadata=metadata,
        )

    # ── shadow ──────────────────────────────────────────────────────

    def shadow(
        self,
        request: GatewayRequest,
        policy: Optional[ExecutionPolicy] = None,
        step_specs=None,
        timeout: float = 1.0,
    ) -> Dict[str, Any]:
        """Bounded shadow analysis. ZERO tools, ZERO writes, never raises.

        The registry is the production registry when wired, otherwise the
        internal diagnostic shadow surface (READ_ONLY + known write
        tools, handlers guarded by ShadowToolExecutionForbidden).
        """
        registry = self._registry or default_shadow_registry()
        runner = ShadowRunner(registry, clock=self._clock,
                              telemetry=self._telemetry)
        return runner.run_shadow(request, policy, step_specs, timeout=timeout)

    def shadow_event(self, event: Any, timeout: float = 1.0) -> Dict[str, Any]:
        """Live-gateway entry for an already-eligible event (§27-32).

        Runs bounded shadow analysis for the event; NEVER raises and
        NEVER produces user-visible output. Any failure is captured as
        ``gateway.v2.shadow.failed`` — the legacy response is untouched.
        """
        try:
            request = self._request_from_event(event)
            return self.shadow(request, step_specs=None, timeout=timeout)
        except Exception as exc:
            self._telemetry.record(SHADOW_FAILED, request_id="evt-unknown",
                                   mode="shadow", reason=str(exc))
            return {"request_id": "evt-unknown", "mode": "shadow", "ok": False,
                    "reason": f"shadow error: {exc}"}

    # ── canary ──────────────────────────────────────────────────────

    def run_canary(
        self,
        request: GatewayRequest,
        policy: Optional[ExecutionPolicy] = None,
        step_specs=None,
        db_path: Optional[str] = None,
        allow_production: bool = False,
    ) -> Dict[str, Any]:
        """Controlled read-only V2 execution. Exactly ONE response."""
        self._telemetry.record(CANARY_STARTED, request_id=request.request_id,
                               mode="canary")
        if not self._flags.enabled or not self._flags.canary:
            self._telemetry.record(CANARY_FAILED, request_id=request.request_id,
                                   reason="not_enabled")
            return self._mapper.map(request.request_id, None) | {
                "code": "V2_NOT_ENABLED"}
        eligible, reason = self._policy.is_eligible(request)
        if not eligible:
            self._telemetry.record(CANARY_FAILED, request_id=request.request_id,
                                   reason=reason)
            return {"request_id": request.request_id, "ok": False,
                    "code": "V2_NOT_ELIGIBLE", "message": reason, "output": None}
        # Sprint 1.0.6.2: canary runs on the production-safe READ_ONLY
        # surface when no production registry is wired at the hook point.
        base_registry = self._registry or default_canary_registry()
        store = self._factory.create_store(db_path=db_path,
                                           allow_production=allow_production)
        if store is None:  # persistence disabled → no durable V2 execution
            return self._mapper.map(request.request_id, None)
        try:
            safe_registry = SafeCanaryToolRegistry(base_registry)
            context = self._builder.build(request)
            orchestrator = RuntimeOrchestrator(store, safe_registry,
                                               clock=self._clock)  # type: ignore[arg-type]
            result = orchestrator.run(context, policy, step_specs)
            response = self._mapper.map(request.request_id, result)
            event = CANARY_COMPLETED if response["ok"] else CANARY_FAILED
            self._telemetry.record(event, request_id=request.request_id,
                                   run_id=result.run_id,
                                   stop_reason=result.stop_reason.value
                                   if result.stop_reason else None)
            response["fallback_allowed"] = self.can_fallback(
                result.run_id, store)[0]
            response["tool_calls"] = self._count_tool_starts(result.run_id, store)
            return response
        except Exception:
            # Caller (canary_event / CLI) decides fallback from the
            # persisted run state; the store is closed in finally.
            raise
        finally:
            store.close()

    @staticmethod
    def _count_tool_starts(run_id: str, store) -> int:
        """ACTUAL attempted tool calls: TOOL_STARTED events in the journal."""
        from agent.execution.events import TOOL_STARTED

        return sum(1 for e in store.list_events(run_id=run_id)
                   if e.event_type == TOOL_STARTED)

    def canary_event(
        self,
        event: Any,
        db_path: Optional[str] = None,
        allow_production: bool = False,
    ) -> Dict[str, Any]:
        """Live-gateway canary entry (Sprint 1.0.6.2 §19/§21-22).

        Returns a controlled dict:
        - ``ok=True`` + ``output_text`` → the hook returns output_text
          (exactly ONE response, V2 is the source of truth);
        - ``ok=False`` + ``fallback_allowed=True`` → no V2 side effect
          exists, the hook may continue the legacy path;
        - ``ok=False`` + ``fallback_allowed=False`` → TOOL_STARTED may
          exist → legacy fallback FORBIDDEN, the hook returns a
          controlled message instead.
        NEVER raises into the gateway.
        """
        store = None
        try:
            request = self._request_from_event(event)
            decision = self.decide(request)
            if decision is not V2Decision.V2_CANARY:
                return {"ok": False, "code": "V2_NOT_ELIGIBLE",
                        "fallback_allowed": True}
            store = self._factory.create_store(
                db_path=db_path, allow_production=allow_production)
            if store is None:
                return {"ok": False, "code": "V2_NOT_ENABLED",
                        "fallback_allowed": True}
            base_registry = self._registry or default_canary_registry()
            safe_registry = SafeCanaryToolRegistry(base_registry)
            context = self._builder.build(request)
            orchestrator = RuntimeOrchestrator(store, safe_registry,
                                               clock=self._clock)  # type: ignore[arg-type]
            result = orchestrator.run(context, None, None)
            response = self._mapper.map(request.request_id, result)
            response["run_id"] = result.run_id
            response["fallback_allowed"] = self.can_fallback(
                result.run_id, store)[0]
            response["tool_calls"] = self._count_tool_starts(result.run_id, store)
            if response.get("ok"):
                response["output_text"] = self._canary_output_text(response)
            return response
        except Exception as exc:
            self._telemetry.record(CANARY_FAILED, request_id="evt-unknown",
                                   reason=str(exc))
            # §22: if ANY persisted run may have TOOL_STARTED, legacy
            # fallback is forbidden — report it conservatively.
            allowed = True
            if store is not None:
                try:
                    for run in store.list_incomplete_runs():
                        ok, _ = self.can_fallback(run.id, store)
                        if not ok:
                            allowed = False
                            break
                except Exception:
                    pass
            return {"ok": False, "code": "V2_EXECUTION_FAILED",
                    "fallback_allowed": allowed,
                    "message": "canary execution failed"}
        finally:
            if store is not None:
                store.close()

    @staticmethod
    def _canary_output_text(response: Dict[str, Any]) -> str:
        """Compact user-safe text from the mapped output {step_id: {...}}."""
        import json as _json

        out = response.get("output") or {}
        if not isinstance(out, dict) or not out:
            return "ok"
        lines = []
        for step_id, value in out.items():
            if isinstance(value, dict):
                lines.append(f"{step_id}: {_json.dumps(value, ensure_ascii=False, default=str)}")
            else:
                lines.append(f"{step_id}: {value}")
        return "\n".join(lines)

    # ── fallback safety (§30) ───────────────────────────────────────

    def can_fallback(
        self,
        run_id: Optional[str] = None,
        store=None,
    ) -> tuple:
        """(allowed, reason). Case A/B allowed; C/D FORBIDDEN."""
        if run_id is None:
            return True, "no_v2_run_created"
        if store is None:
            return False, "store_required"
        for event in store.list_events(run_id=run_id):
            if event.event_type in (TOOL_STARTED, TOOL_COMPLETED):
                return False, "v2_side_effect_possible"
        return True, "zero_tools_started"

    def legacy_fallback(
        self,
        run_id: Optional[str] = None,
        store=None,
    ) -> bool:
        """Attempt legacy fallback; False when forbidden (§30 C/D)."""
        allowed, reason = self.can_fallback(run_id, store)
        if allowed:
            self._telemetry.record(FALLBACK_LEGACY, request_id=run_id,
                                   reason=reason)
        return allowed

    # ── health ──────────────────────────────────────────────────────

    def health(self, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Safe status — no DB paths, no secrets."""
        schema_ready = False
        if db_path:
            try:
                schema_ready = self._factory.schema_ready(db_path)
            except Exception:
                schema_ready = False
        return {
            "runtime_v2": {
                "enabled": self._flags.enabled,
                "shadow": self._flags.shadow,
                "canary": self._flags.canary,
                "persistence": self._flags.persistence,
                "schema_ready": schema_ready,
            },
            "canary_policy": self._policy.summary(),
        }

    @property
    def telemetry(self) -> V2Telemetry:
        return self._telemetry


# Default adapter for the gateway's minimal hook — env flags read once.
gateway_v2_adapter_singleton: Optional[GatewayV2Adapter] = None


def get_default_adapter() -> GatewayV2Adapter:
    global gateway_v2_adapter_singleton
    if gateway_v2_adapter_singleton is None:
        gateway_v2_adapter_singleton = GatewayV2Adapter()
    return gateway_v2_adapter_singleton
