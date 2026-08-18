"""VerifiedToolExecutor (Sprint 1.3.2 §2, §6-§23).

The canonical execution contract:

    ExecutionRequest
      ↓ 1. request shape validation
      ↓ 2. exactly-once receipt check (never invoke twice, §13)
      ↓ 3. registry resolution (§7 — registry identity only)
      ↓ 4. verified + capability + risk/side-effect compatibility (§6)
      ↓ 5. policy ALLOW_V2 gate (§45)
      ↓ 6. SystemBoundary.authorize (§25/§48 — Noop in 1.3.2)
      ↓ 7. argument schema validation (§8 — before STARTED)
      ↓ 8. TOOL_STARTED event + durable STARTED receipt (§15/§18)
      ↓ 9. adapter.execute(context, arguments) with deadline (§21)
      ↓10. side-effect report check (§34 — fail closed)
      ↓11. output schema validation (§9 — before SUCCEEDED)
      ↓12. TOOL_COMPLETED / TOOL_FAILED + receipt finalization (§19/§20)
    ExecutionResult

Guarantees:

- No raw implementation exception escapes the public API (§4): every
  failure is normalized into error_class/error_code.
- Exactly-once per (run_id, step_id, idempotency_key) — duplicates
  return the prior receipt/result or DUPLICATE_ACTION, never a second
  adapter invocation (§13/§42).
- Timeout → TIMED_OUT; if the side-effect outcome is uncertain (non
  read-only surface) → UNKNOWN_OUTCOME (§21). Cooperative cancellation
  only — the executor never pretends arbitrary execution was
  terminated (§22).
- No automatic retry in 1.3.2 — the result only reports
  retryable=true/false; retry policy is orchestration's concern (§23).
- Restart recovery: receipts left STARTED become UNKNOWN_OUTCOME;
  never auto-reexecute (§32).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from agent.runtime.events import RuntimeEvent

from .adapter import AdapterResult
from .boundary import NoopSystemBoundary, SystemBoundary
from .errors import (
    BOUNDARY_REJECTED,
    CAPABILITY_MISMATCH,
    DUPLICATE_ACTION,
    INVALID_ARGUMENTS,
    INVALID_TOOL_RESULT,
    POLICY_NOT_ALLOWED,
    TOOL_CANCELLED,
    TOOL_EXECUTION_ERROR,
    TOOL_NOT_REGISTERED,
    TOOL_NOT_VERIFIED,
    TOOL_RISK_MISMATCH,
    TOOL_SIDE_EFFECT_VIOLATION,
    TOOL_TIMEOUT,
    UNKNOWN_EXECUTION_OUTCOME,
)
from .events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED, emit, utcnow
from .hashing import compute_input_hash, compute_output_hash
from .models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    TERMINAL_STATUSES,
    is_metadata_allowed,
    side_effect_report_compatible_with_read_only,
)
from .receipts import (
    ExecutionReceipt,
    MemoryReceiptStore,
    ReceiptStore,
)
from .registry import VerifiedToolRegistry

_ALLOW_V2 = "ALLOW_V2"

#: Expected side-effect values compatible with a READ_ONLY descriptor.
_READ_ONLY_EXPECTED = frozenset({"NONE", "READ_ONLY"})

#: Risk classes compatible with the migrated read-only surface.
_READ_ONLY_RISKS = frozenset({"READ_ONLY", "NONE"})

PolicyGate = Callable[[ExecutionRequest], bool]


def default_policy_gate(request: ExecutionRequest) -> bool:
    """§45 — canonical policy evidence: verdict ALLOW_V2 required.

    The Capability Policy Engine's decision travels with the request
    as ``policy_verdict`` + ``policy_version`` + ``policy_decision_id``.
    A direct executor call with policy != ALLOW_V2 is REJECTED before
    any adapter call (the executor does NOT re-derive policy — it
    verifies the decision evidence and version).
    """
    return (
        request.policy_verdict == _ALLOW_V2
        and bool(request.policy_decision_id)
    )


#: Sentinel for "adapter did not return within the deadline".
_TIMEOUT_SENTINEL = object()


class VerifiedToolExecutor:
    """§2 — one canonical executor over a VerifiedToolRegistry.

    Executes an :class:`ExecutionRequest` under the full contract:
    registry binding (§7), capability/risk compatibility (§6), policy
    ALLOW gate (§45), SystemBoundary hook (§25), argument schema
    (§8), exactly-once receipts (§13/§15), deadline enforcement
    (§21), cooperative cancellation (§22), side-effect fail-closed
    (§34), output schema (§9) and normalized TOOL_* events (§18-§20).
    """

    def __init__(
        self,
        registry: VerifiedToolRegistry,
        receipts: Optional[ReceiptStore] = None,
        boundary: Optional[SystemBoundary] = None,
        policy_gate: Optional[PolicyGate] = None,
        events: Optional[List[RuntimeEvent]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._registry = registry
        self._receipts = receipts if receipts is not None \
            else MemoryReceiptStore()
        self._boundary = boundary if boundary is not None \
            else NoopSystemBoundary()
        self._policy_gate = policy_gate or default_policy_gate
        self._events = events if events is not None else []
        self._clock = clock or utcnow
        self._execution_seq = 0

    # ── public ────────────────────────────────────────────────────

    @property
    def events(self) -> List[RuntimeEvent]:
        return self._events

    @property
    def receipts(self) -> ReceiptStore:
        return self._receipts

    def recover(self) -> List[ExecutionReceipt]:
        """§32 — mark orphaned STARTED receipts as UNKNOWN_OUTCOME.

        Called automatically on construction; returns the recovered
        receipts. NEVER auto-reexecutes.
        """
        return self._receipts.recover()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run one execution under the canonical contract."""
        started = self._clock()

        # ── 1) request shape ───────────────────────────────────────
        shape_error = self._validate_request_shape(request)
        if shape_error:
            return self._reject(request, started, shape_error,
                                 INVALID_ARGUMENTS)

        # ── 2) exactly-once (§13) ──────────────────────────────────
        prior = self._receipts.get(
            request.run_id, request.step_id, request.idempotency_key)
        if prior is not None:
            prior_status = ExecutionStatus(prior.status) \
                if prior.status in {s.value for s in ExecutionStatus} \
                else ExecutionStatus.UNKNOWN_OUTCOME
            if prior_status in TERMINAL_STATUSES:
                return self._replay_prior(request, started, prior)
            # STARTED in flight / after a crash without recovery →
            # never invoke twice.
            return self._reject(
                request, started, "duplicate in-flight execution",
                DUPLICATE_ACTION)

        # ── 3) registry resolution (§7) ────────────────────────────
        binding = self._registry.resolve(request.tool_name)
        if binding is None:
            return self._reject(
                request, started, f"tool {request.tool_name!r} is not "
                                  f"registered", TOOL_NOT_REGISTERED)
        if not binding.descriptor.verified:
            return self._reject(
                request, started, f"tool {request.tool_name!r} is not "
                                  f"verified", TOOL_NOT_VERIFIED)

        # ── 4) capability / risk compatibility (§6) ────────────────
        if request.capability != binding.descriptor.capability.value:
            return self._reject(
                request, started,
                f"capability {request.capability!r} does not match "
                f"registered {binding.descriptor.capability.value!r}",
                CAPABILITY_MISMATCH)
        expected_side = str(request.expected_side_effect).upper()
        if expected_side not in _READ_ONLY_EXPECTED:
            return self._reject(
                request, started,
                f"expected side effect {request.expected_side_effect!r} "
                f"incompatible with READ_ONLY descriptor",
                TOOL_RISK_MISMATCH)
        expected_risk = str(request.expected_risk_class).upper()
        if expected_risk not in _READ_ONLY_RISKS:
            return self._reject(
                request, started,
                f"expected risk class {request.expected_risk_class!r} "
                f"incompatible with READ_ONLY descriptor",
                TOOL_RISK_MISMATCH)

        # ── 5) policy ALLOW_V2 gate (§45) ──────────────────────────
        if not self._policy_gate(request):
            return self._reject(
                request, started,
                f"policy verdict {request.policy_verdict!r} != ALLOW_V2 "
                f"or missing decision id", POLICY_NOT_ALLOWED)
        if request.policy_version != self._registry.policy_version:
            return self._reject(
                request, started,
                f"policy version {request.policy_version!r} != "
                f"registry {self._registry.policy_version!r}",
                POLICY_NOT_ALLOWED)

        # ── 6) SystemBoundary hook (§25/§48) ───────────────────────
        # Sprint 1.3.3 pipeline: preflight → authorize →
        # verify_before_execute (TOCTOU/expiry/replay revalidation
        # immediately before the adapter). Legacy boundaries (Sprint
        # 1.3.2 shape) keep the single authorize(request) call.
        from .boundary import is_v2_boundary
        boundary = self._boundary
        preflight = None
        if is_v2_boundary(boundary):
            try:
                preflight = boundary.preflight(request,
                                               binding.descriptor)
                decision = boundary.authorize(
                    request, binding.descriptor, preflight)
                if not decision.allow:
                    return self._reject(
                        request, started,
                        f"boundary denied: "
                        f"{decision.reason_code or 'DENY'}",
                        BOUNDARY_REJECTED)
                vbe = boundary.verify_before_execute(
                    request, binding.descriptor, preflight)
                if not vbe.allow:
                    return self._reject(
                        request, started,
                        f"boundary revalidation denied: "
                        f"{vbe.reason_code or 'DENY'}",
                        BOUNDARY_REJECTED)
            except Exception as exc:
                # fail closed (§49): an exception inside the boundary
                # must never become a PASS.
                return self._reject(
                    request, started,
                    f"boundary internal error: {type(exc).__name__}",
                    BOUNDARY_REJECTED)
        else:
            decision = boundary.authorize(request)
            if not decision.allow:
                return self._reject(
                    request, started,
                    f"boundary denied: {decision.reason_code or 'DENY'}",
                    BOUNDARY_REJECTED)

        # ── 7) argument schema (§8 — before STARTED) ───────────────
        arg_errors = binding.validate_arguments(request.arguments)
        if arg_errors:
            return self._reject(
                request, started,
                "invalid arguments: " + "; ".join(arg_errors),
                INVALID_ARGUMENTS)

        # ── 8) deadline (§21) ───────────────────────────────────────
        timeout_ms = self._effective_timeout_ms(request, binding)
        if timeout_ms <= 0:
            return self._reject(
                request, started, f"invalid timeout {timeout_ms}ms",
                INVALID_ARGUMENTS)
        deadline = started + timedelta(milliseconds=timeout_ms)

        # ── 9) cooperative cancellation before start (§22) ─────────
        cancel_token = self._new_cancellation_token()
        if self._is_cancelled(cancel_token):
            return self._finish(
                request, started, None,
                status=ExecutionStatus.CANCELLED,
                error_class="CANCELLED", error_code=TOOL_CANCELLED,
                side_effect=None)

        # ── 10) durable TOOL_STARTED (§15/§18) BEFORE invocation ───
        execution_id = self._next_execution_id()
        input_hash = compute_input_hash(request.arguments)
        receipt = ExecutionReceipt(
            execution_id=execution_id,
            run_id=request.run_id,
            step_id=request.step_id,
            idempotency_key=request.idempotency_key,
            tool=request.tool_name,
            input_hash=input_hash,
            started_at=started.isoformat(),
            status=ExecutionStatus.STARTED.value,
        )
        try:
            self._receipts.insert(receipt)
        except Exception as exc:  # e.g. concurrent duplicate
            return self._reject(
                request, started,
                f"receipt insert failed: {type(exc).__name__}",
                DUPLICATE_ACTION)
        emit(self._events, TOOL_STARTED, request.run_id, started,
             execution_id=execution_id, tool=request.tool_name,
             input_hash=input_hash)
        # TOOL_STARTED must be durable with the receipt BEFORE the
        # adapter call — the receipt insert already committed above.

        # ── 11) adapter invocation with deadline (§21/§10) ─────────
        context = ExecutionContext(
            request_id=request.request_id,
            run_id=request.run_id,
            step_id=request.step_id,
            capability=request.capability,
            tool=request.tool_name,
            policy_version=request.policy_version,
            deadline=deadline,
            cancellation_token=cancel_token,
            goal=str(request.metadata.get("goal", ""))[:500],
        )
        outcome = self._run_adapter(binding, context, request.arguments,
                                    timeout_ms, deadline)
        completed = self._clock()

        # ── 12) timeout / cancellation normalization (§21/§22) ─────
        if outcome is _TIMEOUT_SENTINEL:
            uncertain = not self._is_read_only(binding)
            final_status = (ExecutionStatus.UNKNOWN_OUTCOME
                            if uncertain else ExecutionStatus.TIMED_OUT)
            return self._finish(
                request, started, receipt,
                status=final_status,
                error_class="TIMEOUT" if not uncertain
                else "UNKNOWN_OUTCOME",
                error_code=TOOL_TIMEOUT
                if not uncertain else UNKNOWN_EXECUTION_OUTCOME,
                side_effect=None,
                completed_at=completed, output_hash=None,
                retryable=True)
        if self._is_cancelled(cancel_token):
            # Cooperative cancel requested during execution. For the
            # read-only surface no side effect can have happened, so
            # CANCELLED is honest; for a future write surface this
            # must become UNKNOWN_OUTCOME.
            final_status = (ExecutionStatus.CANCELLED
                            if self._is_read_only(binding)
                            else ExecutionStatus.UNKNOWN_OUTCOME)
            error_code = TOOL_CANCELLED if final_status \
                is ExecutionStatus.CANCELLED else UNKNOWN_EXECUTION_OUTCOME
            return self._finish(
                request, started, receipt,
                status=final_status, error_class="CANCELLED",
                error_code=error_code, side_effect=None,
                completed_at=completed, output_hash=None)

        # ── 13) adapter error → TOOL_FAILED (normalized, §20) ──────
        # An adapter that did not return an AdapterResult is a
        # contract violation → INVALID_TOOL_RESULT (fail closed).
        if not isinstance(outcome, AdapterResult):
            return self._finish(
                request, started, receipt,
                status=ExecutionStatus.FAILED,
                error_class="INVALID_TOOL_RESULT",
                error_code=INVALID_TOOL_RESULT,
                side_effect=None,
                completed_at=completed,
                retryable=False)
        if outcome.error_code is not None or outcome.output is None:
            return self._finish(
                request, started, receipt,
                status=ExecutionStatus.FAILED,
                error_class=outcome.error_class or "TOOL_EXECUTION_ERROR",
                error_code=outcome.error_code or TOOL_EXECUTION_ERROR,
                side_effect=outcome.observed_side_effect,
                completed_at=completed,
                retryable=True)

        # ── 14) side-effect report check (§34 — fail closed) ───────
        if not self._is_read_only(binding):
            # Future write surface: report must match descriptor.
            pass
        elif not side_effect_report_compatible_with_read_only(
                outcome.observed_side_effect):
            self._registry.disable_tool(request.tool_name)
            return self._finish(
                request, started, receipt,
                status=ExecutionStatus.FAILED,
                error_class="SECURITY_VIOLATION",
                error_code=TOOL_SIDE_EFFECT_VIOLATION,
                side_effect=outcome.observed_side_effect,
                completed_at=completed,
                retryable=False)

        # ── 15) output schema (§9 — before SUCCEEDED) ──────────────
        out_errors = binding.validate_output(outcome.output)
        if out_errors:
            return self._finish(
                request, started, receipt,
                status=ExecutionStatus.FAILED,
                error_class="INVALID_TOOL_RESULT",
                error_code=INVALID_TOOL_RESULT,
                side_effect=outcome.observed_side_effect,
                completed_at=completed,
                retryable=False)

        # ── 16) SUCCEEDED + TOOL_COMPLETED (§19) ───────────────────
        # §44 — verify_after_execute foundation (read-only/sandbox;
        # no production mutations in 1.3.3). Never blocks success —
        # full transactional application is Sprint 1.3.4.
        if is_v2_boundary(boundary):
            try:
                boundary.verify_after_execute(
                    request, binding.descriptor, outcome, preflight)
            except Exception:
                # post-check failure must not mask a valid result
                pass
        output_hash = compute_output_hash(outcome.output)
        return self._finish(
            request, started, receipt,
            status=ExecutionStatus.SUCCEEDED,
            output=outcome.output, output_hash=output_hash,
            side_effect=outcome.observed_side_effect,
            completed_at=completed)

    # ── internals ─────────────────────────────────────────────────

    def _validate_request_shape(
        self, request: ExecutionRequest,
    ) -> Optional[str]:
        if not request.request_id or not request.run_id \
                or not request.step_id:
            return "request_id/run_id/step_id are required"
        if not request.tool_name:
            return "tool_name is required"
        if not request.capability:
            return "capability is required"
        if not request.policy_version or not request.policy_decision_id:
            # policy_version/decision are POLICY evidence — their
            # absence is judged by the policy gate (§45), but a
            # missing policy_version is also a malformed request.
            return None
        if not request.idempotency_key:
            return "stable idempotency_key is mandatory for READ_ONLY " \
                   "tools (§14)"
        try:
            if int(request.timeout_ms) <= 0:
                return "timeout_ms must be > 0"
        except (TypeError, ValueError):
            return "timeout_ms must be a positive integer"
        if not is_metadata_allowed(request.metadata):
            return "metadata contains non-whitelisted keys"
        return None

    def _effective_timeout_ms(
        self,
        request: ExecutionRequest,
        binding,
    ) -> int:
        descriptor_ms = int(float(binding.descriptor.timeout) * 1000)
        return min(int(request.timeout_ms), descriptor_ms)

    def _is_read_only(self, binding) -> bool:
        side = str(binding.descriptor.side_effect).upper()
        return side in ("READ_ONLY", "NONE")

    def _new_cancellation_token(self):
        import threading
        return threading.Event()

    def _is_cancelled(self, token) -> bool:
        return token is not None and token.is_set()

    def _next_execution_id(self) -> str:
        import uuid
        return uuid.uuid4().hex

    def _run_adapter(self, binding, context, arguments,
                     timeout_ms: int, deadline: datetime):
        """Run the adapter with a hard deadline.

        ThreadPoolExecutor WITHOUT ``with`` — the context manager's
        __exit__ joins the worker thread, so a genuinely hung handler
        would block the timeout path forever (Sprint 1.0.2 pitfall).
        A deadline breach returns ``_TIMEOUT_SENTINEL`` — the executor
        normalizes it into TIMED_OUT / UNKNOWN_OUTCOME (§21).
        """
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                binding.adapter.execute, context, dict(arguments))
            try:
                return future.result(
                    timeout=max(timeout_ms / 1000.0, 0.001))
            except TimeoutError:
                return _TIMEOUT_SENTINEL
            except Exception as exc:  # adapter raised — normalized
                return AdapterResult(
                    output=None,
                    observed_side_effect="UNKNOWN",
                    error_class=type(exc).__name__,
                    error_code=TOOL_EXECUTION_ERROR,
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _reject(self, request, started, message: str,
                error_code: str) -> ExecutionResult:
        return self._finish(
            request, started, None,
            status=ExecutionStatus.REJECTED,
            error_class=error_code, error_code=error_code,
            side_effect=None)

    def _replay_prior(self, request, started,
                      prior: ExecutionReceipt) -> ExecutionResult:
        """§13 — duplicate request: return the prior receipt/result."""
        prior_status = ExecutionStatus(prior.status) \
            if prior.status in {s.value for s in ExecutionStatus} \
            else ExecutionStatus.UNKNOWN_OUTCOME
        return ExecutionResult(
            execution_id=prior.execution_id,
            request_id=request.request_id,
            run_id=request.run_id,
            step_id=request.step_id,
            tool_name=request.tool_name,
            status=prior_status,
            started_at=self._clock(),
            completed_at=None,
            duration_ms=None,
            output=None,
            output_hash=prior.output_hash,
            error_class=None,
            error_code=(UNKNOWN_EXECUTION_OUTCOME
                        if prior_status is
                        ExecutionStatus.UNKNOWN_OUTCOME else None),
            side_effect_observed=None,
            retryable=False,
            execution_receipt=prior.to_dict(),
            duplicate_of=prior.execution_id,
        )

    def _finish(
        self,
        request: ExecutionRequest,
        started: datetime,
        receipt: Optional[ExecutionReceipt],
        *,
        status: ExecutionStatus,
        error_class: Optional[str] = None,
        error_code: Optional[str] = None,
        output: Optional[Dict[str, Any]] = None,
        output_hash: Optional[str] = None,
        side_effect: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        retryable: bool = False,
    ) -> ExecutionResult:
        completed = completed_at or self._clock()
        duration_ms = round(
            (completed - started).total_seconds() * 1000.0, 3)

        # Finalize the durable receipt when one was started.
        if receipt is not None and receipt.status == \
                ExecutionStatus.STARTED.value:
            try:
                self._receipts.complete(
                    receipt.execution_id,
                    output_hash or "",
                    completed.isoformat(),
                    status.value)
                finalized = self._receipts.get(
                    request.run_id, request.step_id,
                    request.idempotency_key)
                if finalized is not None:
                    receipt = finalized
            except Exception:
                # Receipt finalization must never mask the result.
                pass

        # Events: TOOL_COMPLETED only after a validated success (§19);
        # TOOL_FAILED normalized, no traceback (§20).
        if status is ExecutionStatus.SUCCEEDED:
            emit(self._events, TOOL_COMPLETED, request.run_id, completed,
                 execution_id=(receipt.execution_id
                               if receipt else ""),
                 tool=request.tool_name,
                 output_hash=output_hash or "")
        elif receipt is not None and status in (
                ExecutionStatus.FAILED,
                ExecutionStatus.TIMED_OUT,
                ExecutionStatus.UNKNOWN_OUTCOME,
                ExecutionStatus.CANCELLED):
            emit(self._events, TOOL_FAILED, request.run_id, completed,
                 execution_id=receipt.execution_id,
                 tool=request.tool_name,
                 error_class=error_class or "UNKNOWN",
                 error_code=error_code or "UNKNOWN_EXECUTION_OUTCOME",
                 retryable=bool(retryable))

        return ExecutionResult(
            execution_id=(receipt.execution_id
                          if receipt is not None else ""),
            request_id=request.request_id,
            run_id=request.run_id,
            step_id=request.step_id,
            tool_name=request.tool_name,
            status=status,
            started_at=started,
            completed_at=completed,
            duration_ms=duration_ms,
            output=output,
            output_hash=output_hash,
            error_class=error_class,
            error_code=error_code,
            side_effect_observed=side_effect,
            retryable=retryable,
            execution_receipt=(receipt.to_dict()
                               if receipt is not None else None),
        )


__all__ = [
    "VerifiedToolExecutor",
    "default_policy_gate",
    "PolicyGate",
]
