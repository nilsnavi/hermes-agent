"""Sandbox tool registry (Sprint 1.3.5 §18).

Sandbox mutation tools are registered ONLY through this registry —
no dynamic imports/path/eval. The registry follows the Sprint 1.3.2
VerifiedToolRegistry pattern (ToolBinding + schema validation) but the
sandbox surface is side-effecting by design
(side_effect != READ_ONLY), with capabilities:

    SANDBOX_FILE_MUTATION
    SANDBOX_SERVICE_CONTROL

Production SYSTEM_CONTROL capability is never used here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SANDBOX_FILE_MUTATION = "SANDBOX_FILE_MUTATION"
SANDBOX_SERVICE_CONTROL = "SANDBOX_SERVICE_CONTROL"

TOOLS = (
    "sandbox_file_create",
    "sandbox_file_write",
    "sandbox_file_delete",
    "sandbox_file_chmod",
    "sandbox_service_start",
    "sandbox_service_stop",
    "sandbox_service_restart",
    "sandbox_service_reload",
)

TOOL_CAPABILITY = {
    "sandbox_file_create": SANDBOX_FILE_MUTATION,
    "sandbox_file_write": SANDBOX_FILE_MUTATION,
    "sandbox_file_delete": SANDBOX_FILE_MUTATION,
    "sandbox_file_chmod": SANDBOX_FILE_MUTATION,
    "sandbox_service_start": SANDBOX_SERVICE_CONTROL,
    "sandbox_service_stop": SANDBOX_SERVICE_CONTROL,
    "sandbox_service_restart": SANDBOX_SERVICE_CONTROL,
    "sandbox_service_reload": SANDBOX_SERVICE_CONTROL,
}


@dataclass(frozen=True)
class SandboxToolMetadata:
    tool_name: str
    capability: str
    side_effect: str = "MUTATION"  # never READ_ONLY
    verified: bool = True
    sandbox_scoped: bool = True
    timeout: float = 30.0
    approval_required: bool = True
    argument_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "capability": self.capability,
            "side_effect": self.side_effect,
            "verified": self.verified,
            "sandbox_scoped": self.sandbox_scoped,
            "timeout": self.timeout,
            "approval_required": self.approval_required,
            "argument_schema": self.argument_schema,
        }


@dataclass
class SandboxToolBinding:
    metadata: SandboxToolMetadata
    operation: str  # SandboxOperation value
    handler: Optional[Callable] = None  # bound at execution time

    def to_dict(self) -> Dict[str, Any]:
        return {"metadata": self.metadata.to_dict(),
                "operation": self.operation}


class SandboxToolRegistry:
    """Verified registry of the sandbox mutation surface (§18)."""

    def __init__(self) -> None:
        self._bindings: Dict[str, SandboxToolBinding] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        ops = {
            "sandbox_file_create": "CREATE_FILE",
            "sandbox_file_write": "WRITE_FILE",
            "sandbox_file_delete": "DELETE_FILE",
            "sandbox_file_chmod": "CHMOD",
            "sandbox_service_start": "START_SANDBOX_SERVICE",
            "sandbox_service_stop": "STOP_SANDBOX_SERVICE",
            "sandbox_service_restart": "RESTART_SANDBOX_SERVICE",
            "sandbox_service_reload": "RELOAD_SANDBOX_SERVICE",
        }
        for tool in TOOLS:
            self._bindings[tool] = SandboxToolBinding(
                metadata=SandboxToolMetadata(
                    tool_name=tool,
                    capability=TOOL_CAPABILITY[tool],
                    argument_schema={
                        "target": {"type": "string", "required": True},
                        "content": {"type": "string"},
                        "mode": {"type": "integer"},
                    },
                ),
                operation=ops[tool],
            )

    def has(self, tool_name: str) -> bool:
        return tool_name in self._bindings

    def resolve(self, tool_name: str) -> Optional[SandboxToolBinding]:
        return self._bindings.get(tool_name)

    def names(self) -> List[str]:
        return sorted(self._bindings)

    def metadata(self, tool_name: str) -> SandboxToolMetadata:
        binding = self._bindings.get(tool_name)
        if binding is None:
            raise KeyError(tool_name)
        return binding.metadata

    def operation_for(self, tool_name: str) -> str:
        binding = self._bindings.get(tool_name)
        if binding is None:
            raise KeyError(tool_name)
        return binding.operation

    def validate_arguments(self, tool_name: str,
                           arguments: Dict[str, Any]) -> List[str]:
        """Schema validation — unknown/extra keys are rejected."""
        meta = self.metadata(tool_name)
        errors = []
        schema = meta.argument_schema
        for key, spec in schema.items():
            if spec.get("required") and key not in arguments:
                errors.append(f"missing required argument: {key}")
        for key in arguments:
            if key not in schema:
                errors.append(f"unknown argument: {key}")
        return errors

    def summary(self) -> Dict[str, Any]:
        return {
            "tools": self.names(),
            "capabilities": sorted(set(TOOL_CAPABILITY.values())),
            "all_side_effecting": all(
                self._bindings[t].metadata.side_effect != "READ_ONLY"
                for t in self._bindings),
        }
