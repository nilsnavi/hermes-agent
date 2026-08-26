"""Provenance tracking.

Every written, forgotten, and consolidated memory record carries an immutable
provenance: who created it, from which source, in which scope, at what time,
and for what consolidation generation. Provenance is append-only at the value
boundary — records are frozen, and the workflow attaches provenance at write
time so a memory item can never be "born" without a traceable origin.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import MemoryProvenanceError


class ProvenanceSource(Enum):
    USER = "user"
    AGENT = "agent"
    CONSOLIDATION = "consolidation"
    IMPORT = "import"


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    source: ProvenanceSource
    actor_id: str
    created_at: float
    generation: int

    def __post_init__(self) -> None:
        if type(self.source) is not ProvenanceSource:
            raise MemoryProvenanceError("source must be an exact ProvenanceSource value")
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise MemoryProvenanceError("actor_id must be a non-empty string")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise MemoryProvenanceError("created_at must be a number")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise MemoryProvenanceError("generation must be a non-negative integer")

    def child(self, *, source: ProvenanceSource, actor_id: str, now: float) -> "ProvenanceRecord":
        """Provenance of a derived (consolidated) record — generation+1."""
        if self.created_at > now:
            raise MemoryProvenanceError("consolidation timestamp predates origin")
        return ProvenanceRecord(
            source=source,
            actor_id=actor_id,
            created_at=now,
            generation=self.generation + 1,
        )