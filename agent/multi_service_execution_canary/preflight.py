"""Read-only production evidence preflight."""
from __future__ import annotations
import dataclasses
@dataclasses.dataclass(frozen=True,slots=True)
class PreflightEvidence:
 baseline_exact:bool;registry_exact:bool;graph_healthy:bool;identity_valid:bool;system_control_off:bool;generic_service_control_denied:bool;real_adapter_disabled:bool
 @property
 def passed(self):return all(dataclasses.astuple(self))
