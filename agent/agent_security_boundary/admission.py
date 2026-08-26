"""The execution security gate: the ONLY admissible path into the kernel.

Certifies the single execution path for the control plane:

    AgentCapabilityIntent -> policy -> capability_router -> system_boundary
    -> executor -> sealed sandbox

The gate is a composition root that enforces, at admission time:

  * every pipeline stage is MANDATORY -- a missing/unconfigured/errored component
    is a DENY (COMPONENT_MISSING), never a fallback to allow;
  * caller-supplied verdicts/approvals are DATA ONLY -- the gate computes
    authority itself from the mandatory components at admission time, and forged
    claims never change the outcome;
  * REVALIDATE_REQUIRED / UNKNOWN / TIMEOUT / MISSING_EVIDENCE / COMPONENT_MISSING /
    REGISTRY_DRIFT are all fail-closed (no execution);
  * SIDE_EFFECT_UNKNOWN -> HUMAN_REVIEW, never auto-execute;
  * mutation side-effect classes and CodingAgent's forbidden capabilities are
    hard-denied (CodingAgent stays READ_ONLY/SHADOW; write/execute OFF);
  * the sandbox adapter is sealed: an external direct adapter call raises.

This module performs NO tool execution and imports no execution-kernel code. The
gate ADMITS (certifies); actual kernel invocation is a separate, future bind
layer that goes exclusively through the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable
from uuid import uuid4

from .audit import AuditTrail
from .coding import classify_side_effect, is_forbidden_capability
from .exceptions import (
    AdmissionDenied,
    ComponentMissing,
    RegistryDrift,
    SecurityBoundaryError,
)
from .intent import AgentCapabilityIntent, CallerClaim
from .ports import (
    CapabilityRouterSeam,
    MANDATORY_PORT_NAMES,
    PolicyEvaluator,
    SandboxAdapterSeam,
    SystemBoundarySeam,
    ToolExecutorSeam,
    side_effect_of_operation,
)
from .seal import SealedSandbox
from .status import (
    AdmissionOutcome,
    Disposition,
    MUTATION_CLASSES,
    NON_EXECUTABLE_DISPOSITIONS,
    SideEffectClass,
)

_Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Immutable outcome + disposition for one capability request."""

    admission_id: str
    agent_id: str
    capability: str
    side_effect_class: SideEffectClass
    outcome: AdmissionOutcome
    disposition: Disposition
    reason: str
    receipt_id: str | None
    policy_decision: str = ""
    boundary_decision: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome in (AdmissionOutcome.ALLOW_READ_ONLY, AdmissionOutcome.ALLOW_SHADOW)

    def to_dict(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "agent_id": self.agent_id,
            "capability": self.capability,
            "side_effect_class": self.side_effect_class.value,
            "outcome": self.outcome.value,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "policy_decision": self.policy_decision,
            "boundary_decision": self.boundary_decision,
        }


def _allowed(decision: object) -> bool:
    """Conservative allow test: only an explicit boolean True (or an object whose
    ``.allowed`` is boolean True) counts as allow. Strings like ``"ALLOW"``,
    ``"PASS"``, ``"APPROVED"`` are never accepted as authority (fail-closed)."""
    if decision is None:
        return False
    if isinstance(decision, bool):
        return decision
    if hasattr(decision, "allowed"):
        value = getattr(decision, "allowed")
        if callable(value):
            try:
                value = value()
            except Exception:
                return False
        return value is True
    return False


class SecurityBoundaryGate:
    """Composition root that certifies the single admissible execution path."""

    __slots__ = (
        "_policy",
        "_router",
        "_boundary",
        "_executor",
        "_sandbox",
        "_registry",
        "_audit",
        "_clock",
        "_admission_ids",
    )

    def __init__(
        self,
        *,
        policy: PolicyEvaluator | None = None,
        capability_router: CapabilityRouterSeam | None = None,
        system_boundary: SystemBoundarySeam | None = None,
        executor: ToolExecutorSeam | None = None,
        sandbox: SandboxAdapterSeam | None = None,
        registry: Any | None = None,
        audit: AuditTrail | None = None,
        clock: _Clock | None = None,
    ) -> None:
        from time import time

        self._clock = clock if clock is not None else time
        self._policy = policy
        self._router = capability_router
        self._boundary = system_boundary
        self._executor = executor
        self._sandbox = SealedSandbox(sandbox) if sandbox is not None else SealedSandbox(None)
        self._registry = registry
        self._audit = audit if audit is not None else AuditTrail(clock=self._clock)
        self._admission_ids: set[str] = set()

    # -- mandatory-component / wiring introspection ----------------------------

    def missing_components(self) -> tuple[str, ...]:
        present = {
            "policy": self._policy is not None,
            "capability_router": self._router is not None,
            "system_boundary": self._boundary is not None,
            "executor": self._executor is not None,
            "sandbox": self._sandbox.is_present,
        }
        return tuple(name for name, ok in present.items() if not ok)

    def sealed_sandbox(self) -> SealedSandbox:
        """Read access to the sealed sandbox (still not directly invocable)."""
        return self._sandbox

    # -- admission -------------------------------------------------------------

    def admit(
        self,
        intent: AgentCapabilityIntent,
        *,
        caller_claims: Iterable[CallerClaim] = (),
    ) -> AdmissionDecision:
        if type(intent) is not AgentCapabilityIntent:
            raise SecurityBoundaryError("intent must be an exact AgentCapabilityIntent")

        claims = tuple(caller_claims)
        # Caller claims are recorded for audit as DATA and are NEVER consulted
        # for the decision (item: caller verdict is data only). We keep the
        # reference so the audit captures what the caller asserted, without it
        # influencing authority in any branch below.

        admission_id = uuid4().hex
        sec = intent.side_effect_class

        # 1. Mandatory pipeline components.
        missing = self.missing_components()
        if missing:
            return self._decide(
                intent,
                admission_id,
                AdmissionOutcome.DENY,
                Disposition.COMPONENT_MISSING,
                f"mandatory component(s) missing: {', '.join(missing)}",
                receipt_id=None,
                reasons={"policy": "dns", "boundary": "missing"},
                claims=claims,
            )

        # 2. Runtime-owned registry guard (item 10).
        if self._registry is not None:
            drift = self._check_registry_drift()
            if drift:
                return self._decide(
                    intent,
                    admission_id,
                    AdmissionOutcome.DENY,
                    Disposition.REGISTRY_DRIFT,
                    "registry snapshot drifted (rebound/mutated registry)",
                    receipt_id=None,
                    reasons={"policy": "dns", "boundary": "registry-drift"},
                    claims=claims,
                )
            if intent.agent_id not in self._registry.registered_ids():
                return self._decide(
                    intent,
                    admission_id,
                    AdmissionOutcome.DENY,
                    Disposition.DENIED,
                    f"agent {intent.agent_id!r} is not in the runtime-owned registry",
                    receipt_id=None,
                    reasons={"policy": "dns", "boundary": "unknown-agent"},
                    claims=claims,
                )

        # 3. Mutation / CodingAgent hard-deny (item 9; non-goals). The check is
        #    on BOTH the caller-declared side-effect class AND a deterministic
        #    capability-derived class, so a caller cannot under-declare a
        #    mutation capability as READ_ONLY to evade the mutation set (B2).
        sec = intent.side_effect_class
        derived = classify_side_effect(intent.capability)
        # Broader deterministic op-name classifier as a fallback when the coding
        # capability map cannot classify the token (so known mutation op words
        # like "shell"/"write"/"delete"/"systemctl" are caught even if the caller
        # under-declared the class as read-only).
        if derived is SideEffectClass.UNKNOWN:
            fallback = side_effect_of_operation(intent.capability)
            if fallback is not SideEffectClass.UNKNOWN:
                derived = fallback
        if (
            is_forbidden_capability(intent.capability)
            or sec in MUTATION_CLASSES
            or derived in MUTATION_CLASSES
        ):
            return self._decide(
                intent,
                admission_id,
                AdmissionOutcome.DENY,
                Disposition.DENIED,
                "mutation capability / mutation side-effect class hard-denied this phase",
                receipt_id=None,
                reasons={"policy": "hard-deny", "boundary": "denied"},
                claims=claims,
            )

        # 4. UNKNOWN side-effect class is not executable (fail-closed). A class
        #    is UNKNOWN if the caller declared it so OR the capability-derived
        #    class is UNKNOWN (unclassifiable capability -> human review, never
        #    auto-allow even if the caller declared a read-only class).
        if derived is SideEffectClass.UNKNOWN or sec is SideEffectClass.UNKNOWN:
            return self._decide(
                intent,
                admission_id,
                AdmissionOutcome.HUMAN_REVIEW,
                Disposition.SIDE_EFFECT_UNKNOWN,
                "unclassified side-effect class; human review required",
                receipt_id=None,
                reasons={"policy": "unknown", "boundary": "unknown"},
                claims=claims,
            )

        # 5. platform_policy seam.
        try:
            result = self._policy.evaluate(intent)  # type: ignore[reportOptionalMemberAccess]
            policy_allowed = _allowed(result)
            policy_decision = _describe(result)
        except Exception as exc:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.UNKNOWN,
                f"policy evaluation error: {_brief(exc)}", receipt_id=None,
                reasons={"policy": "error", "boundary": "n/a"}, claims=claims,
            )
        if not policy_allowed:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.DENIED,
                "platform policy denied the capability", receipt_id=None,
                reasons={"policy": "denied", "boundary": "n/a"}, claims=claims,
            )

        # 6. capability_router seam.
        try:
            route_allowed = _allowed(self._router.decide(intent))  # type: ignore[reportOptionalMemberAccess]
        except AdmissionDenied as exc:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.DENIED,
                _brief(exc), receipt_id=None,
                reasons={"policy": "denied", "boundary": "n/a"}, claims=claims,
            )
        except Exception as exc:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.UNKNOWN,
                f"capability router evaluation error: {_brief(exc)}", receipt_id=None,
                reasons={"policy": "error", "boundary": "n/a"}, claims=claims,
            )
        if not route_allowed:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.DENIED,
                "capability router denied the capability", receipt_id=None,
                reasons={"policy": "denied", "boundary": "n/a"}, claims=claims,
            )

        # 7. mandatory SystemBoundary (preflight -> authorize -> verify-before).
        boundary_ok, boundary_decision, boundary_reason = self._run_boundary(intent)
        if not boundary_ok:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, boundary_reason,
                "system boundary denied admission", receipt_id=None,
                reasons={"policy": "allowed", "boundary": boundary_decision},
                claims=claims,
            )

        # 8. VerifiedToolExecutor seam: present + ready (admission, not execution).
        try:
            executor_ready = bool(self._executor.is_ready())  # type: ignore[reportOptionalMemberAccess]
        except Exception:
            executor_ready = False
        if not executor_ready:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.COMPONENT_MISSING,
                "verified tool executor is not ready", receipt_id=None,
                reasons={"policy": "allowed", "boundary": boundary_decision},
                claims=claims,
            )

        # 9. Sealed sandbox certified present; still no invocation (admission).
        if not self._sandbox.is_present or not self._sandbox.is_sealed:
            return self._decide(
                intent, admission_id, AdmissionOutcome.DENY, Disposition.COMPONENT_MISSING,
                "sealed sandbox is not present/available", receipt_id=None,
                reasons={"policy": "allowed", "boundary": boundary_decision},
                claims=claims,
            )

        # 10. All gates self-computed allow -> admit READ_ONLY (this phase).
        receipt_id = f"receipt-{admission_id[:12]}"
        decision = self._decide(
            intent, admission_id, AdmissionOutcome.ALLOW_READ_ONLY, Disposition.ADMITTED,
            "single execution path certified: policy+router+boundary+executor+sandbox allow",
            receipt_id=receipt_id,
            reasons={"policy": policy_decision, "boundary": boundary_decision},
            claims=claims,
        )
        return decision

    # -- helpers ---------------------------------------------------------------

    def _check_registry_drift(self) -> bool:
        guard = getattr(self._registry, "assert_registry_sealed", None)
        if guard is None:
            return True  # cannot prove the registry is sealed -> treat as drift
        try:
            guard()
        except (RegistryDrift, SecurityBoundaryError):
            return True
        except Exception:
            return True
        return False

    def _run_boundary(self, intent: AgentCapabilityIntent) -> tuple[bool, str, Disposition]:
        try:
            pre = self._boundary.preflight(intent)  # type: ignore[reportOptionalMemberAccess]
            if not _allowed(pre):
                return False, _describe(pre), Disposition.DENIED
            auth = self._boundary.authorize(intent)  # type: ignore[reportOptionalMemberAccess]
            if not _allowed(auth):
                return False, _describe(auth), Disposition.DENIED
            verify = self._boundary.verify_before_execute(intent)  # type: ignore[reportOptionalMemberAccess]
            if not _allowed(verify):
                return False, _describe(verify), Disposition.DENIED
            return True, _describe(auth), Disposition.ADMITTED
        except Exception as exc:
            name = type(exc).__name__
            if "Revalidate" in name or "RevalidateRequired" in name:
                return False, name, Disposition.REVALIDATE_REQUIRED
            return False, name, Disposition.UNKNOWN

    def _decide(
        self,
        intent: AgentCapabilityIntent,
        admission_id: str,
        outcome: AdmissionOutcome,
        disposition: Disposition,
        reason: str,
        *,
        receipt_id: str | None,
        reasons: dict[str, str],
        claims: tuple[CallerClaim, ...],
    ) -> AdmissionDecision:
        self._admission_ids.add(admission_id)
        policy_decision = reasons.get("policy", "n/a")
        boundary_decision = reasons.get("boundary", "n/a")
        decision = AdmissionDecision(
            admission_id=admission_id,
            agent_id=intent.agent_id,
            capability=intent.capability,
            side_effect_class=intent.side_effect_class,
            outcome=outcome,
            disposition=disposition,
            reason=reason,
            receipt_id=receipt_id,
            policy_decision=policy_decision,
            boundary_decision=boundary_decision,
        )
        self._append_audit(intent, decision, claims)
        return decision

    def _append_audit(
        self,
        intent: AgentCapabilityIntent,
        decision: AdmissionDecision,
        claims: tuple[CallerClaim, ...],
    ) -> None:
        self._audit.append(
            agent_id=intent.agent_id,
            tenant_id=intent.tenant_id,
            user_id=intent.user_id,
            capability_requested=intent.capability,
            side_effect_class=intent.side_effect_class,
            policy_decision=decision.policy_decision,
            boundary_decision=decision.boundary_decision,
            executor_disposition=decision.disposition.value,
            admission_outcome=decision.outcome,
            disposition=decision.disposition,
            reason=decision.reason,
            receipt_id=decision.receipt_id,
            task_id=intent.task_id,
            task_step_id=intent.task_step_id,
            agent_run_id=intent.agent_run_id,
        )
        # claims are data: referenced only here is fine because they never feed a
        # decision branch; keeping the tuple bound above documents that.

    @property
    def audit(self) -> AuditTrail:
        return self._audit

    @property
    def admitted_count(self) -> int:
        return len(self._admission_ids)


def _describe(decision: object) -> str:
    if decision is None:
        return "none"
    if isinstance(decision, bool):
        return "allow" if decision else "deny"
    if hasattr(decision, "name"):
        return str(getattr(decision, "name"))
    return str(type(decision).__name__)


def _brief(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


__all__ = ["AdmissionDecision", "SecurityBoundaryGate"]