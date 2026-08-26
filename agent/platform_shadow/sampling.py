"""Bounded shadow sampling policy (Phase 7 §6).

Modes: OFF (default), SAMPLE (deterministic hash key: tenant | task kind |
request hash), FULL_SHADOW. A user-controlled boolean such as ``shadow=true`` on
a payload is NEVER treated as authority: sampling is decided ONLY by keying at
the shadow boundary, never by anything the caller/tenant supplies as a claim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .exceptions import ShadowSamplingError
from .models import ShadowSamplingMode, ShadowTaskEnvelope


def _request_hash(env: ShadowTaskEnvelope) -> str:
    payload = "|".join(
        (env.shadow_id, env.source_request_id, env.tenant_id,
         env.user_id, env.task_kind, env.input_digest)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SamplingResult:
    sampled: bool
    mode: ShadowSamplingMode
    reason: str


class ShadowSampler:
    """Deterministic bounded sampler; NO caller/tenant authority input."""

    __slots__ = ("_mode", "_sample_rate_per_mille", "_included_task_kinds", "_criteria")

    def __init__(
        self,
        *,
        mode: ShadowSamplingMode = ShadowSamplingMode.OFF,
        sample_rate_per_mille: int = 0,
        included_task_kinds: frozenset[str] = frozenset(),
    ) -> None:
        if type(mode) is not ShadowSamplingMode:
            raise ShadowSamplingError("mode must be an exact ShadowSamplingMode value")
        if not isinstance(sample_rate_per_mille, int) or not (0 <= sample_rate_per_mille <= 1000):
            raise ShadowSamplingError("sample_rate_per_mille must be in [0, 1000]")
        self._mode = mode
        self._sample_rate_per_mille = sample_rate_per_mille
        self._included_task_kinds = included_task_kinds
        self._criteria = ("sampler-boundary",)

    def mode(self) -> ShadowSamplingMode:
        return self._mode

    def sample(self, env: ShadowTaskEnvelope) -> SamplingResult:
        """Decide whether to take this task into shadow (bounded, deterministic).

        ``OFF`` -> never sampled. ``FULL_SHADOW`` -> always sampled (task-kind
        filtered if given). ``SAMPLE`` -> the sampler's OWN key hash falls within
        the rate; the caller can neither force nor suppress sampling here.
        """
        if type(env) is not ShadowTaskEnvelope:
            raise ShadowSamplingError("env must be an exact ShadowTaskEnvelope value")

        if self._mode is ShadowSamplingMode.OFF:
            return SamplingResult(False, self._mode, "mode=off")

        if self._included_task_kinds and env.task_kind not in self._included_task_kinds:
            return SamplingResult(False, self._mode, "task-kind excluded")

        if self._mode is ShadowSamplingMode.FULL_SHADOW:
            return SamplingResult(True, self._mode, "mode=full_shadow")

        # SAMPLE: deterministic key hash lane in [0,1000).
        lane = int(_request_hash(env)[:8], 16) % 1000
        sampled = lane < self._sample_rate_per_mille
        if not sampled:
            return SamplingResult(
                False, self._mode, f"rate={self._sample_rate_per_mille} per mille (lane {lane})"
            )
        return SamplingResult(True, self._mode, f"rate={self._sample_rate_per_mille} per mille long")


__all__ = ["SamplingResult", "ShadowSampler"]