"""Calibration observe-safety barrier (Sprint 1.1.1.1 §3-§8/§11).

Execution-boundary guard for INTERNAL_SYNTHETIC calibration requests.

Problem (proven in Sprint 1.1.1 O-runs):
  The Intent Router in OBSERVE mode only *classifies and recommends*.
  O6 ("перезапусти Hermes gateway") and O7 ("запускай эту проверку
  каждый час") showed that a calibration request can still reach the
  LEGACY pipeline and REALLY execute side effects (gateway restart via
  a written script; a real cron job + watchdog script), because the
  router is non-authoritative by design.

This module adds the missing layer: an explicit calibration safety
context that makes the EXECUTION BOUNDARY deny/simulate every
side-effecting action while the router remains a pure classifier.

Invariant (§11):
  CALIBRATION REQUEST → classify → recommend → optionally exercise a
  READ_ONLY tool → side-effecting execution FORBIDDEN.

Fail-closed: any unknown/ambiguous disposition resolves to DENY.
Nothing in this module can execute, spawn, write, or call a tool.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CalibrationDisposition(Enum):
    """Execution-boundary verdict for one calibration request.

    - ALLOW_READ_ONLY: classification is read-only; a read-only tool
      MAY be exercised (nothing else).
    - SIMULATE: the action would otherwise happen; report what would
      have run, execute nothing.
    - DENY: execution is forbidden outright.
    - NO_EXECUTION: unknown/unclassifiable → nothing runs.
    """

    ALLOW_READ_ONLY = "allow_read_only"
    SIMULATE = "simulate"
    DENY = "deny"
    NO_EXECUTION = "no_execution"


class CalibrationReason(Enum):
    """Structured reason codes for barrier verdicts."""

    CALIBRATION_CONTEXT = "calibration_context"
    READ_ONLY_INTENT = "read_only_intent"
    WRITE_DENIED = "calibration_write_denied"
    DELETE_DENIED = "calibration_delete_denied"
    SYSTEM_DENIED = "calibration_system_denied"
    SCHEDULE_DENIED = "calibration_schedule_denied"
    APPROVAL_NO_MUTATION = "calibration_approval_no_mutation"
    UNKNOWN_NO_EXECUTION = "calibration_unknown_no_execution"
    SYSTEM_CONTROL_COMMAND = "system_control_command"
    SCHEDULER_MUTATION = "scheduler_mutation"


#: Intent families the classifier can produce (value strings from
#: models.IntentType — no import of the gateway model needed to keep
#: this module standalone and import-safe).
READ_ONLY_INTENTS = {
    "conversation",
    "summarization",
    "information_read",
    "status_read",
    "search_read",
    "analysis",
    "planning",
    "code_assist",
    "diagnostic",
}

#: Intent → disposition when a calibration context is active.
#: WRITE is SIMULATE (reversible-class actions may be "dry run"
#: reported), DELETE/SYSTEM/SCHEDULE are DENY (never simulated as
#: real), APPROVAL_ACTION is NO mutation (the ops path may be
#: classified but can never mutate approval state), UNKNOWN → nothing.
_INTENT_DISPOSITION: Dict[str, CalibrationDisposition] = {
    "write_action": CalibrationDisposition.SIMULATE,
    "delete_action": CalibrationDisposition.DENY,
    "system_action": CalibrationDisposition.DENY,
    "schedule_action": CalibrationDisposition.DENY,
    "approval_action": CalibrationDisposition.NO_EXECUTION,
    "unknown": CalibrationDisposition.NO_EXECUTION,
}

#: System-control command families (fail-closed, §4). Matched against
#: the RESOLVED command string; any hit → DENY from inside the
#: gateway/runtime process. External operator runbook is the ONLY
#: allowed production restart path.
_SYSTEM_CONTROL_PATTERNS = (
    ("restart", ("restart",)),
    ("stop", ("stop",)),
    ("kill", ("kill", "pkill", "killall")),
    ("systemctl_mutate", ("systemctl",)),
    ("service_mutate", ("service",)),
)

#: Scheduler mutation verbs (§7): create/update/delete jobs.
_SCHEDULER_MUTATIONS = {"create", "update", "delete", "remove", "pause",
                        "resume"}


@dataclass(frozen=True)
class CalibrationSafetyContext:
    """Explicit calibration safety context (§3).

    ``sample_source`` names the provenance; ``observe_calibration`` is
    the master switch. With it False (ordinary LIVE traffic) the
    barrier is inert and every request is ALLOW_READ_ONLY-equivalent
    (the router itself stays the only decision layer for live traffic).
    """

    sample_source: str = "INTERNAL_SYNTHETIC"
    observe_calibration: bool = True
    request_id: str = ""


@dataclass(frozen=True)
class CalibrationVerdict:
    """One execution-boundary verdict (immutable)."""

    disposition: CalibrationDisposition
    intent: str
    reason_codes: List[str] = field(default_factory=list)
    simulated_action: Optional[str] = None
    context: Optional[CalibrationSafetyContext] = None

    @property
    def allowed_read_only(self) -> bool:
        return self.disposition is CalibrationDisposition.ALLOW_READ_ONLY

    @property
    def denied(self) -> bool:
        return self.disposition in (
            CalibrationDisposition.DENY,
            CalibrationDisposition.NO_EXECUTION,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "intent": self.intent,
            "reason_codes": list(self.reason_codes),
            "simulated_action": self.simulated_action,
            "sample_source": self.context.sample_source if self.context else None,
            "observe_calibration": bool(
                self.context and self.context.observe_calibration
            ),
            "request_id": self.context.request_id if self.context else None,
        }


class CalibrationSafetyBarrier:
    """Execution-boundary gate for calibration requests.

    Pure decision logic — no I/O, no tools, no side effects. Callers
    (gateway hook / calibration harness) are responsible for honoring
    the verdict; the barrier itself only returns it.
    """

    VERSION = "barrier-v1"

    def evaluate(
        self,
        decision: object,
        context: Optional[CalibrationSafetyContext] = None,
    ) -> CalibrationVerdict:
        """Map a router decision to an execution-boundary verdict.

        ``decision`` is duck-typed (intent / expected_side_effect /
        recommended_route attributes) so the barrier works with the
        router's IntentRoutingDecision and with plain dicts in tests.
        """
        ctx = context or CalibrationSafetyContext()
        if not ctx.observe_calibration:
            # Inert for live traffic: the router remains the only layer.
            return CalibrationVerdict(
                disposition=CalibrationDisposition.ALLOW_READ_ONLY,
                intent=str(getattr(decision, "intent", "unknown")),
                reason_codes=[CalibrationReason.CALIBRATION_CONTEXT.value],
                context=ctx,
            )

        intent = str(getattr(decision, "intent", "unknown") or "unknown")
        side_effect = str(
            getattr(decision, "expected_side_effect", "") or ""
        )

        # Disposition precedence (§2/§3): intent families with
        # operational consequences are resolved FIRST, before any
        # side-effect based read-only handling. An APPROVAL_ACTION (or
        # DELETE/SYSTEM/SCHEDULE/WRITE/UNKNOWN) must NEVER become
        # ALLOW_READ_ONLY just because expected_side_effect=NONE —
        # "no side effect declared" is not the same as "read-only".
        disposition = _INTENT_DISPOSITION.get(intent)
        if disposition is not None:
            reason = {
                CalibrationDisposition.SIMULATE:
                    CalibrationReason.WRITE_DENIED,
                CalibrationDisposition.DENY:
                    self._deny_reason(intent),
            }.get(disposition)
            if reason is None:
                # NO_EXECUTION: distinguish approval (no mutation) from
                # genuinely unknown (nothing runs).
                reason = (
                    CalibrationReason.APPROVAL_NO_MUTATION
                    if intent == "approval_action"
                    else CalibrationReason.UNKNOWN_NO_EXECUTION
                )
            return CalibrationVerdict(
                disposition=disposition,
                intent=intent,
                reason_codes=[reason.value],
                simulated_action=(
                    f"{intent} (calibration dry-run)" if
                    disposition is CalibrationDisposition.SIMULATE else None
                ),
                context=ctx,
            )

        # Side-effect based read-only handling (lowest precedence):
        # only intents OUTSIDE the unsafe families may be allowed as
        # read-only by their declared side effect.
        if intent in READ_ONLY_INTENTS or side_effect in (
            "read_only", "none"
        ):
            return CalibrationVerdict(
                disposition=CalibrationDisposition.ALLOW_READ_ONLY,
                intent=intent,
                reason_codes=[CalibrationReason.READ_ONLY_INTENT.value],
                context=ctx,
            )

        # Fail-closed: unknown intent family → nothing executes.
        return CalibrationVerdict(
            disposition=CalibrationDisposition.NO_EXECUTION,
            intent=intent,
            reason_codes=[CalibrationReason.UNKNOWN_NO_EXECUTION.value],
            context=ctx,
        )

    @staticmethod
    def _deny_reason(intent: str) -> CalibrationReason:
        if intent == "delete_action":
            return CalibrationReason.DELETE_DENIED
        if intent == "system_action":
            return CalibrationReason.SYSTEM_DENIED
        if intent == "schedule_action":
            return CalibrationReason.SCHEDULE_DENIED
        return CalibrationReason.WRITE_DENIED


class SystemControlGuard:
    """Fail-closed gateway/service control guard (§4).

    Any command that would restart/stop/kill the gateway or mutate a
    systemd unit is DENIED when it originates from inside the
    gateway/runtime process. External operator runbook remains the
    only allowed production restart path.
    """

    VERSION = "system-guard-v1"

    #: Words that mark a command line as system control. Matched on
    #: whole tokens (word boundaries) of the RESOLVED command string.
    _MUTATING_VERBS = (
        "restart", "stop", "kill", "pkill", "killall", "reboot",
        "shutdown", "poweroff",
    )
    _UNIT_TOKENS = ("hermes-gateway", "hermes-gateway.service",
                    "hermes-agent", "hermes")

    def check_command(self, command: str) -> Optional[CalibrationVerdict]:
        """Return a DENY verdict when *command* is system control.

        ``None`` means the command is not system control (caller may
        proceed with the rest of the barrier logic).
        """
        if not command or not isinstance(command, str):
            return None
        low = command.lower()
        # systemctl with a mutating verb + gateway unit.
        if "systemctl" in low and any(
            v in low for v in self._MUTATING_VERBS
        ) and any(u in low for u in self._UNIT_TOKENS):
            return self._deny(CalibrationReason.SYSTEM_CONTROL_COMMAND,
                              "systemctl mutate hermes unit")
        # Bare mutating verbs targeting hermes/python (kill/pkill/killall).
        import re as _re

        for verb in ("pkill", "killall"):
            if _re.search(rf"(^|\s){verb}(\s|$)", low) and any(
                u in low for u in self._UNIT_TOKENS
            ):
                return self._deny(CalibrationReason.SYSTEM_CONTROL_COMMAND,
                                  f"{verb} hermes process")
        # kill <pid> (numeric) — self-termination of the runtime process.
        if _re.search(r"(^|\s)kill\s+[0-9]+(\s|$)", low):
            return self._deny(CalibrationReason.SYSTEM_CONTROL_COMMAND,
                              "kill PID")
        if _re.search(r"(^|\s)kill(\s|$)", low) and any(
            u in low for u in self._UNIT_TOKENS
        ):
            return self._deny(CalibrationReason.SYSTEM_CONTROL_COMMAND,
                              "kill hermes process")
        # service <name> restart|stop (start-of-line or after whitespace).
        if _re.search(r"(^|\s)service(\s|$)", low) and any(
            v in low for v in ("restart", "stop")
        ) and any(u in low for u in self._UNIT_TOKENS):
            return self._deny(CalibrationReason.SYSTEM_CONTROL_COMMAND,
                              "service mutate hermes unit")
        return None

    @staticmethod
    def _deny(reason: CalibrationReason, action: str) -> CalibrationVerdict:
        return CalibrationVerdict(
            disposition=CalibrationDisposition.DENY,
            intent="system_action",
            reason_codes=[reason.value],
            simulated_action=None,
        )


class SchedulerGuard:
    """Scheduler mutation guard (§7).

    With observe_calibration=true, create/update/delete of scheduled
    jobs is DENIED at the execution boundary. SCHEDULE_ACTION may still
    be classified by the router — the scheduler mutation is zero.
    """

    VERSION = "scheduler-guard-v1"

    def check_scheduler_action(
        self,
        action: str,
        observe_calibration: bool = True,
    ) -> Optional[CalibrationVerdict]:
        """DENY when *action* would mutate the scheduler.

        ``None`` = not a mutation (or barrier inactive) → caller may
        proceed.
        """
        if not observe_calibration:
            return None
        if not action or not isinstance(action, str):
            return None
        verb = action.strip().lower().split()[0] if action.strip() else ""
        if verb in _SCHEDULER_MUTATIONS:
            return CalibrationVerdict(
                disposition=CalibrationDisposition.DENY,
                intent="schedule_action",
                reason_codes=[CalibrationReason.SCHEDULER_MUTATION.value],
                simulated_action=None,
            )
        return None


__all__ = [
    "CalibrationDisposition",
    "CalibrationReason",
    "CalibrationSafetyContext",
    "CalibrationVerdict",
    "CalibrationSafetyBarrier",
    "SystemControlGuard",
    "SchedulerGuard",
]
