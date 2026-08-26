"""System Agent Runtime layer — Phase 4 of the Hermes 2.0 control plane.

```
                 +---------------------- Control Plane ----------------------+
                 |  agent/agent_system/   (System Agent Runtime)              |
                 |                                                            |
                 |  definitions  -> first system agents (data, no process)    |
                 |  capabilities -> declarative surface (metadata != grant)   |
                 |  health       -> fail-closed readiness signal              |
                 |  context      -> sanitized AgentExecutionContext builder   |
                 |  runtime      -> registry + lifecycle + health bookkeeping |
                 |  coordination -> ties into agent_orchestration (Phase 2)   |
                 |                                                            |
                 |  reuses: agent_runtime contracts (registry/lifecycle/ctx)  |
                 +------------------------------------------------------------+
                                  |
                                  v  NEVER executes / dispatches / grants
                 +------------------------------------------------------------+
                 |  Existing Execution Kernel  (unchanged, not imported here)  |
                 +------------------------------------------------------------+
```

No-authority invariants (auditable):

* capability declaration != execution authority;
* agent metadata != permission grant;
* AgentMessage == data, not a grant;
* Memory == data, not authority;
* Planner != executor; Supervisor != executor;
* the layer imports no execution-kernel module and exposes no
  execute/dispatch/authorize/grant surface.

This package is standalone (stdlib + sibling control-plane contracts) and holds
NO production activation: it registers nothing into production, changes no
production capabilities, and performs no tool execution.
"""

from .capabilities import (
    CANONICAL_CAPABILITIES,
    CapabilityDeclaration,
    CapabilitySurface,
    SystemCapability,
    declare_capabilities,
)
from .context import ContextAssembler, ContextSpec
from .coordination import SystemAgentCoordination
from .definitions import (
    SYSTEM_IMPLEMENTATION_IDS,
    SystemAgentRole,
    build_system_agent_definitions,
    system_agent_definition,
    system_agent_role,
)
from .exceptions import (
    AgentHealthError,
    AgentRegistryDrift,
    CapabilityDeclarationError,
    ContextAssemblyError,
    SystemAgentCoordinationError,
    SystemAgentError,
    UnknownImplementation,
    UnknownSystemAgent,
)
from .health import (
    AgentAdmissionStatus,
    AgentHealthModel,
    AgentHealthReport,
    AgentHealthStatus,
)
from .runtime import SystemAgentRuntime

__all__ = [
    "AgentAdmissionStatus",
    "AgentHealthError",
    "AgentHealthModel",
    "AgentHealthReport",
    "AgentHealthStatus",
    "AgentRegistryDrift",
    "CANONICAL_CAPABILITIES",
    "CapabilityDeclaration",
    "CapabilityDeclarationError",
    "CapabilitySurface",
    "ContextAssembler",
    "ContextAssemblyError",
    "ContextSpec",
    "SYSTEM_IMPLEMENTATION_IDS",
    "SystemAgentCoordination",
    "SystemAgentCoordinationError",
    "SystemAgentError",
    "SystemAgentRole",
    "SystemAgentRuntime",
    "SystemCapability",
    "UnknownImplementation",
    "UnknownSystemAgent",
    "build_system_agent_definitions",
    "declare_capabilities",
    "system_agent_definition",
    "system_agent_role",
]