"""Verified tool registry binding (Sprint 1.3.2 §6-§9).

The executor resolves tools ONLY through this registry — no arbitrary
tool names, no dynamic import, no string eval, no shell/PATH lookup,
no plugin discovery (§7). Registry binding is mandatory.

Each binding ties a tool name to:

- the verified :class:`CapabilityRegistry` descriptor (the single
  source of truth for capability / side effect / risk / timeout);
- the tool adapter (§10) that executes it;
- an explicit ARGUMENT schema (§8) validated BEFORE STARTED;
- an explicit OUTPUT schema (§9) validated BEFORE SUCCEEDED.

Construction cross-validates every binding against the capability
registry (tool must exist, verified, READ_ONLY-compatible) — any
drift raises BEFORE anything can execute.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.capability_router.registry import (
    CapabilityRegistry,
    RegistryEntry,
    RegistryValidationError,
)

from .adapter import VerifiedToolAdapter
from .errors import (
    INVALID_ARGUMENTS,
    INVALID_TOOL_RESULT,
    TOOL_NOT_REGISTERED,
    TOOL_NOT_VERIFIED,
    TOOL_RISK_MISMATCH,
    TOOL_SIDE_EFFECT_VIOLATION,
)
from .models import (
    side_effect_report_compatible_with_read_only,
)

# ── lightweight schema vocabulary (stdlib-only) ────────────────────

#: Valid scalar types in argument/output schemas.
SCALAR_TYPES = ("str", "int", "bool", "float", "list", "dict")


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def validate_schema_value(
    field_name: str,
    value: Any,
    spec: Dict[str, Any],
) -> Optional[str]:
    """Validate one value against a field spec.

    Spec keys: ``type`` (scalar type name), ``required`` (bool),
    ``allowed`` (closed list of allowed values), ``min``/``max``
    (int bounds). Returns an error message or None.
    """
    spec_type = spec.get("type", "str")
    if spec_type not in SCALAR_TYPES:
        return f"unknown schema type {spec_type!r} for {field_name}"
    if value is None:
        return None if not spec.get("required") else \
            f"{field_name} is required"
    if _type_name(value) != spec_type:
        return f"{field_name} must be {spec_type}, got " \
               f"{_type_name(value)}"
    allowed = spec.get("allowed")
    if allowed is not None and value not in allowed:
        return f"{field_name} must be one of {sorted(allowed)}"
    if spec_type == "int":
        if spec.get("min") is not None and value < spec["min"]:
            return f"{field_name} must be >= {spec['min']}"
        if spec.get("max") is not None and value > spec["max"]:
            return f"{field_name} must be <= {spec['max']}"
    if spec_type == "str" and spec.get("max_len") is not None:
        if len(value) > spec["max_len"]:
            return f"{field_name} exceeds max length " \
                   f"{spec['max_len']}"
    return None


def validate_against_schema(
    schema: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[str]:
    """Validate a payload against ``{"fields": {...}}``.

    Returns a list of error messages (empty = valid). Unknown keys are
    rejected (fail closed) — the schema is explicit.
    """
    errors: List[str] = []
    fields = schema.get("fields", {})
    payload = dict(payload or {})
    for key in payload:
        if key not in fields:
            errors.append(f"unknown key {key!r}")
    for key, spec in fields.items():
        err = validate_schema_value(key, payload.get(key), spec)
        if err:
            errors.append(err)
    return errors


#: Default argument schema: no arguments allowed.
EMPTY_ARGUMENT_SCHEMA: Dict[str, Any] = {"fields": {}}

#: Default output schema: any dict (bounded by the tool contract).
ANY_DICT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "fields": {"output": {"type": "dict", "required": True}},
}


def _check_read_only_descriptor(entry: RegistryEntry) -> None:
    """§6/§34 — the migrated surface is READ_ONLY only."""
    side = str(entry.side_effect).upper()
    if side not in ("READ_ONLY", "NONE"):
        raise RegistryValidationError(
            f"tool {entry.tool_name} side effect {side} is not "
            f"READ_ONLY — out of the 1.3.2 migrated surface")


@dataclass(frozen=True)
class ToolBinding:
    """One registry binding: descriptor + adapter + schemas."""

    tool_name: str
    descriptor: RegistryEntry
    adapter: VerifiedToolAdapter
    argument_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)

    def validate_arguments(self, arguments: Dict[str, Any]) -> List[str]:
        return validate_against_schema(self.argument_schema, arguments)

    def validate_output(self, output: Any) -> List[str]:
        if not isinstance(output, dict):
            return [f"output must be a dict, got {_type_name(output)}"]
        schema = self.output_schema
        fields = schema.get("fields", {})
        if "output" in fields and fields["output"].get("type") == "dict":
            # ANY_DICT_OUTPUT_SCHEMA — only require a dict, which we
            # already checked.
            return []
        return validate_against_schema(schema, output)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "descriptor": self.descriptor.to_dict(),
            "argument_schema": self.argument_schema,
            "output_schema": self.output_schema,
        }


class VerifiedToolRegistry:
    """§6-§9 — registry-bound execution surface.

    ``capability_registry`` is the Sprint 1.3.0 CapabilityRegistry
    (the single source of verified descriptors). Bindings are added
    per tool; every binding is cross-validated at bind time.
    """

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
    ) -> None:
        self._cap_registry = capability_registry or CapabilityRegistry()
        self._bindings: Dict[str, ToolBinding] = {}

    # ── binding ────────────────────────────────────────────────────

    def bind(
        self,
        tool_name: str,
        adapter: VerifiedToolAdapter,
        argument_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> "VerifiedToolRegistry":
        """Bind one tool. Raises RegistryValidationError on any §27
        drift (unknown tool / unverified / non-read-only)."""
        entry = self._cap_registry.entry_for_tool(tool_name)
        if entry is None:
            raise RegistryValidationError(
                f"tool {tool_name} has no CapabilityRegistry descriptor")
        if not entry.verified:
            raise RegistryValidationError(
                f"tool {tool_name} is not verified")
        _check_read_only_descriptor(entry)
        self._bindings[tool_name] = ToolBinding(
            tool_name=tool_name,
            descriptor=entry,
            adapter=adapter,
            argument_schema=argument_schema or EMPTY_ARGUMENT_SCHEMA,
            output_schema=output_schema or ANY_DICT_OUTPUT_SCHEMA,
        )
        return self

    # ── resolution (§7 — registry identity only) ───────────────────

    def has(self, tool_name: str) -> bool:
        return tool_name in self._bindings

    def resolve(self, tool_name: str) -> Optional[ToolBinding]:
        """Registry identity required — returns the binding or None."""
        return self._bindings.get(tool_name)

    def binding(self, tool_name: str) -> ToolBinding:
        binding = self._bindings.get(tool_name)
        if binding is None:
            raise KeyError(tool_name)
        return binding

    def names(self) -> List[str]:
        return sorted(self._bindings)

    # ── policy evidence ────────────────────────────────────────────

    @property
    def policy_version(self) -> str:
        """The canonical policy version the registry is bound to."""
        return "cap-policy-v1"

    # ── disabled routes (§34 fail-closed) ──────────────────────────

    def disable_tool(self, tool_name: str) -> None:
        """Disable a V2 tool route after a side-effect violation (§34).

        A disabled tool can never execute again for the process
        lifetime — resolve() returns None, so the executor reports
        TOOL_NOT_REGISTERED (fail closed).
        """
        self._bindings.pop(tool_name, None)

    def summary(self) -> Dict[str, Any]:
        return {
            "tools": self.names(),
            "policy_version": self.policy_version,
            "bindings": {
                name: b.to_dict()
                for name, b in sorted(self._bindings.items())
            },
        }


__all__ = [
    "ToolBinding",
    "VerifiedToolRegistry",
    "validate_against_schema",
    "validate_schema_value",
    "EMPTY_ARGUMENT_SCHEMA",
    "ANY_DICT_OUTPUT_SCHEMA",
    "SCALAR_TYPES",
]
