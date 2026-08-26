"""Agent observation / result model (Phase 6 §14).

Agent output is DATA. ``AgentObservation`` carries only findings and metadata;
there is NO ``execute``, ``approved`` or ``grant`` field with authority
semantics. A ``requested_capability`` is a request (an intent to be re-admitted
through the boundary), never a grant. Patch/observation payloads are canonical
plain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_MAX_TEXT_LENGTH = 65_536
_MAX_FACTS = 256
_MAX_CITATIONS = 256


def _require_bounded_text(name: str, value: str, *, optional: bool = False) -> str:
    if value is None or (optional and value == ""):
        return "" if optional else value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")
    return value


@dataclass(frozen=True, slots=True)
class Citation:
    """A provenance pointer (data only; no authority)."""

    source: str
    reference: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _require_bounded_text("source", self.source))
        object.__setattr__(
            self, "reference", _require_bounded_text("reference", self.reference, optional=True)
        )


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """Immutable, data-only output of one read-only agent run."""

    agent_run_id: str
    agent_id: str
    summary: str
    facts: tuple[str, ...] = ()
    confidence: float = 0.5
    citations: tuple[Citation, ...] = ()
    recommended_next_step: str = ""
    requested_capability: str = ""  # an INTENT to be re-admitted, never a grant

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_run_id", _require_bounded_text("agent_run_id", self.agent_run_id))
        object.__setattr__(self, "agent_id", _require_bounded_text("agent_id", self.agent_id))
        object.__setattr__(self, "summary", _require_bounded_text("summary", self.summary))
        for fact in self.facts:
            _require_bounded_text("fact", fact)
        if len(self.facts) > _MAX_FACTS:
            raise ValueError(f"facts exceed {_MAX_FACTS} items")
        if type(self.citations) is not tuple or len(self.citations) > _MAX_CITATIONS:
            raise ValueError(f"citations must be a tuple of at most {_MAX_CITATIONS}")
        for citation in self.citations:
            if type(citation) is not Citation:
                raise ValueError("citations must hold exact Citation values")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise ValueError("confidence must be a finite number in [0, 1]")
        object.__setattr__(
            self,
            "recommended_next_step",
            _require_bounded_text("recommended_next_step", self.recommended_next_step, optional=True),
        )
        object.__setattr__(
            self,
            "requested_capability",
            _require_bounded_text("requested_capability", self.requested_capability, optional=True),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_run_id": self.agent_run_id,
            "agent_id": self.agent_id,
            "summary": self.summary,
            "facts": self.facts,
            "confidence": self.confidence,
            "citations": [{"source": c.source, "reference": c.reference} for c in self.citations],
            "recommended_next_step": self.recommended_next_step,
            "requested_capability": self.requested_capability,
            "authority_semantics": False,  # explicit: this result has NO authority
        }


__all__ = [
    "AgentObservation",
    "Citation",
]