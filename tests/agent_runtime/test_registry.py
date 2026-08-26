from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.agent_runtime import AgentPermissions
from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry


class MutableString(str):
    matches: bool

    def __new__(cls, value: str) -> "MutableString":
        instance = super().__new__(cls, value)
        instance.matches = True
        return instance

    def __eq__(self, other: object) -> bool:
        return self.matches and super().__eq__(other)

    __hash__ = str.__hash__


def definition(**overrides: object) -> AgentDefinition:
    values: dict[str, object] = {
        "agent_id": "research-agent",
        "version": 1,
        "name": "Research Agent",
        "role": "researcher",
        "implementation_id": "research-agent-v1",
        "capabilities": ("research",),
        "trust_score": 0.5,
        "permissions": AgentPermissions(read_files=True),
    }
    values.update(overrides)
    return AgentDefinition(**values)  # type: ignore[arg-type]


def test_registers_first_version_and_returns_immutable_definition() -> None:
    registry = AgentRegistry(["research-agent-v1"])
    registered = registry.register(definition())

    assert registered == definition()
    assert registered.key == ("research-agent", 1)
    assert registry.get("research-agent", 1) == registered
    with pytest.raises(FrozenInstanceError):
        registered.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_id", ""),
        ("agent_id", "   "),
        ("agent_id", "x" * 65_537),
        ("version", True),
        ("version", 0),
        ("name", ""),
        ("name", "x" * 65_537),
        ("role", "   "),
        ("implementation_id", "module.factory"),
        ("implementation_id", "module:factory"),
        ("implementation_id", "path/to-agent"),
        ("implementation_id", "agent name"),
        ("implementation_id", "agent;run"),
        ("capabilities", []),
        ("capabilities", ()),
        ("capabilities", ("research", "research")),
        ("capabilities", ("",)),
        ("capabilities", tuple(str(i) for i in range(257))),
        ("trust_score", True),
        ("trust_score", -0.01),
        ("trust_score", 1.01),
        ("trust_score", float("nan")),
        ("trust_score", float("inf")),
        ("permissions", object()),
    ],
)
def test_definition_rejects_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        definition(**{field: value})


def test_definition_requires_exact_permissions_type() -> None:
    class DerivedPermissions(AgentPermissions):
        pass

    with pytest.raises(ValueError):
        definition(permissions=DerivedPermissions())


def test_registry_rejects_unapproved_implementation_and_non_first_version() -> None:
    registry = AgentRegistry(["research-agent-v1"])

    with pytest.raises(ValueError):
        registry.register(definition(implementation_id="other-agent"))
    with pytest.raises(ValueError):
        registry.register(definition(version=2))


def test_versions_must_be_contiguous_and_queries_are_exact_and_sorted() -> None:
    registry = AgentRegistry(["research-agent-v1", "research-agent-v2", "writer-agent"])
    research_v1 = registry.register(definition())
    writer_v1 = registry.register(
        definition(agent_id="writer", implementation_id="writer-agent")
    )
    research_v2 = registry.register(
        definition(version=2, implementation_id="research-agent-v2")
    )

    assert registry.latest("research-agent") == research_v2
    assert registry.get("research-agent", 1) == research_v1
    assert registry.list() == (research_v1, research_v2, writer_v1)
    assert registry.snapshot() == registry.list()
    with pytest.raises(KeyError):
        registry.get("research-agent", 3)
    with pytest.raises(KeyError):
        registry.latest("missing")
    with pytest.raises(ValueError):
        registry.register(definition(version=2, implementation_id="research-agent-v2"))
    with pytest.raises(ValueError):
        registry.register(definition(version=4, implementation_id="research-agent-v2"))


def test_allowlist_is_copied_and_only_safe_identifiers_are_accepted() -> None:
    allowed = {"research-agent-v1"}
    registry = AgentRegistry(allowed)
    allowed.clear()

    assert registry.register(definition()) == definition()
    for invalid in ("module.factory", "module:factory", "path/to", "has space", "agent;run"):
        with pytest.raises(ValueError):
            AgentRegistry([invalid])


def test_registry_has_no_mutating_or_loading_surface() -> None:
    registry = AgentRegistry(["research-agent-v1"])

    for forbidden in ("update", "unregister", "replace", "load", "resolve", "import_module"):
        assert not hasattr(registry, forbidden)


def test_registry_copies_definitions_on_input_and_every_public_output() -> None:
    registry = AgentRegistry(["research-agent-v1"])
    supplied = definition()
    registered = registry.register(supplied)

    object.__setattr__(supplied, "name", "corrupted input")
    object.__setattr__(registered, "name", "corrupted return")
    object.__setattr__(registered.permissions, "read_files", False)
    fetched = registry.get("research-agent", 1)
    assert fetched.name == "Research Agent"
    assert fetched.permissions.read_files is True

    for returned in (fetched, registry.latest("research-agent"), registry.list()[0], registry.snapshot()[0]):
        object.__setattr__(returned, "role", "corrupted output")
        assert registry.get("research-agent", 1).role == "researcher"


def test_registry_normalizes_string_subclasses_before_storage() -> None:
    aliased_id = MutableString("research-agent")
    registry = AgentRegistry([MutableString("research-agent-v1")])
    registered = registry.register(definition(agent_id=aliased_id))

    aliased_id.matches = False

    assert type(registered.agent_id) is str
    assert registry.get("research-agent", 1).agent_id == "research-agent"


def test_registry_uses_slots_and_hides_old_publicish_store_names() -> None:
    registry = AgentRegistry(["research-agent-v1"])

    assert not hasattr(registry, "__dict__")
    assert not hasattr(registry, "_definitions")
    assert not hasattr(registry, "_allowed_implementation_ids")


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get", ("", 1)),
        ("get", ("x" * 65_537, 1)),
        ("get", ("research-agent", True)),
        ("get", ("research-agent", 0)),
        ("get", ("research-agent", 1.0)),
        ("latest", ("",)),
        ("latest", ("x" * 65_537,)),
    ],
)
def test_registry_queries_reject_malformed_boundaries(method: str, args: tuple[object, ...]) -> None:
    registry = AgentRegistry(["research-agent-v1"])
    registry.register(definition())

    with pytest.raises(AgentContractError):
        getattr(registry, method)(*args)


def test_failed_registration_is_atomic() -> None:
    registry = AgentRegistry(["research-agent-v1", "research-agent-v2"])
    registry.register(definition())
    before = registry.snapshot()

    with pytest.raises(AgentContractError):
        registry.register(definition(version=2, implementation_id="not-allowed"))
    assert registry.snapshot() == before

    with pytest.raises(AgentContractError):
        registry.register(definition(version=3, implementation_id="research-agent-v2"))
    assert registry.snapshot() == before
