"""Auditable provider-neutral routing contracts."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RoutePurpose(str, Enum):
    MAIN = "main"
    COMPRESSION = "compression"
    VISION = "vision"
    TITLE = "title"
    SEARCH = "search"


@dataclass(frozen=True)
class RouteDecision:
    provider: str
    model: str
    endpoint: Optional[str]
    api_mode: str
    credential_reference: Optional[str]
    route_purpose: RoutePurpose


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    AUTHENTICATION = "authentication"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_INTERNAL = "provider_internal"
    UNKNOWN = "unknown"


class FallbackDisposition(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass(frozen=True)
class FallbackPolicy:
    dispositions: tuple[tuple[FailureClass, FallbackDisposition], ...] = ()

    def __post_init__(self):
        if len({c for c, _ in self.dispositions}) != len(self.dispositions):
            raise ValueError("duplicate fallback policy classification")

    def disposition(self, classification):
        return dict(self.dispositions).get(classification, FallbackDisposition.DENIED)


@dataclass(frozen=True)
class RouteCandidate:
    provider: str
    model: str
    credential_reference: Optional[str]
    purpose: RoutePurpose
    precedence: int

    def __post_init__(self):
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("malformed route candidate provider")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("malformed route candidate model")
        if not isinstance(self.precedence, int) or isinstance(self.precedence, bool) or self.precedence < 0:
            raise ValueError("invalid precedence")
        if not isinstance(self.purpose, RoutePurpose):
            raise ValueError("invalid route purpose")
        if self.credential_reference is not None and not isinstance(self.credential_reference, str):
            raise ValueError("invalid credential reference")

    @property
    def identity(self):
        return (self.provider, self.model, self.credential_reference, self.purpose)


@dataclass(frozen=True)
class FailureEvidence:
    classification: FailureClass
    reason_code: str
    candidate: RouteCandidate

    def __post_init__(self):
        if not isinstance(self.classification, FailureClass):
            raise ValueError("invalid failure classification")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("invalid failure reason")
        if not isinstance(self.candidate, RouteCandidate):
            raise ValueError("invalid failure candidate")


class RoutingStatus(str, Enum):
    ROUTED = "routed"
    NO_ROUTE = "no_route"
    EXHAUSTED = "exhausted"
    FALLBACK_NOT_ALLOWED = "fallback_not_allowed"


@dataclass(frozen=True)
class RoutingResult:
    status: RoutingStatus
    candidate: Optional[RouteCandidate]
    reason_code: str

    def __post_init__(self):
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("invalid routing reason")
        if self.status is RoutingStatus.ROUTED and self.candidate is None:
            raise ValueError("routed result requires candidate")
        if self.status in (RoutingStatus.NO_ROUTE, RoutingStatus.EXHAUSTED) and self.candidate is not None:
            raise ValueError("terminal result cannot contain candidate")


@dataclass(frozen=True)
class RoutePlan:
    candidates: tuple[RouteCandidate, ...]
    policy: FallbackPolicy = FallbackPolicy()

    def __post_init__(self):
        if self.candidates and len({c.purpose for c in self.candidates}) != 1:
            raise ValueError("mixed-purpose route plan")
        if len({c.identity for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate logical route candidate")
        object.__setattr__(self, "candidates", tuple(sorted(self.candidates, key=lambda c: (c.precedence, c.provider, c.model, c.credential_reference or ""))))

    def first(self):
        return self.candidates[0] if self.candidates else None

    def select(self):
        if not self.candidates:
            return RoutingResult(RoutingStatus.NO_ROUTE, None, "no_legal_candidates")
        return RoutingResult(RoutingStatus.ROUTED, self.candidates[0], "selected")

    def fallback(self, failed, evidence):
        if failed not in self.candidates:
            return RoutingResult(RoutingStatus.FALLBACK_NOT_ALLOWED, None, "failed_candidate_not_in_plan")
        if evidence.candidate != failed:
            return RoutingResult(RoutingStatus.FALLBACK_NOT_ALLOWED, failed, "evidence_candidate_mismatch")
        if self.policy.disposition(evidence.classification) is FallbackDisposition.DENIED:
            return RoutingResult(RoutingStatus.FALLBACK_NOT_ALLOWED, failed, "fallback_denied")
        index = self.candidates.index(failed)
        if index + 1 >= len(self.candidates):
            return RoutingResult(RoutingStatus.EXHAUSTED, None, "candidates_exhausted")
        return RoutingResult(RoutingStatus.ROUTED, self.candidates[index + 1], "fallback_selected")
