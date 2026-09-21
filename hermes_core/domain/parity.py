"""Normalized, sensitive-data-free differential observations."""
from dataclasses import dataclass
from enum import Enum
class ParityClass(str,Enum): MATCH="MATCH"; INTENTIONAL_DELTA="INTENTIONAL_DELTA"; UNVERIFIED="UNVERIFIED"; NOT_APPLICABLE="NOT_APPLICABLE"
@dataclass(frozen=True)
class ParityObservation:
 slice:str; scenario:str; legacy_outcome:str; core_outcome:str; classification:ParityClass; reason_code:str; legacy_provenance:str="UNVERIFIED"; core_provenance:str="executed_core"
 def __post_init__(self):
  if not isinstance(self.classification,ParityClass): raise ValueError("classification_invalid")
  if not all(isinstance(v,str) and v.strip() for v in (self.slice,self.scenario,self.legacy_outcome,self.core_outcome,self.reason_code,self.legacy_provenance,self.core_provenance)): raise ValueError("observation_invalid")
  if self.classification is ParityClass.MATCH and (self.legacy_outcome == "UNVERIFIED" or self.legacy_provenance == "UNVERIFIED"): raise ValueError("match_requires_verified_legacy")
