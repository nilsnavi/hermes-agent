"""ContextAssembler tests: sanitized, bounded context; capability footprint fail-closed."""

import pytest

from agent.agent_runtime.models import AgentExecutionContext

from agent.agent_system.capabilities import CapabilitySurface, SystemCapability, declare_capabilities
from agent.agent_system.context import ContextAssembler, ContextSpec
from agent.agent_system.exceptions import ContextAssemblyError, UnknownSystemAgent


def _research_surface():
    return declare_capabilities(
        "research",
        capabilities=(SystemCapability.RESEARCH, SystemCapability.COORDINATION),
        description="read-only research agent",
    )


def _spec(**overrides):
    base = {
        "task_id": "t-1",
        "step_id": "s-1",
        "run_id": "r-1",
        "input": "query",
    }
    base.update(overrides)
    return ContextSpec(**base)  # type: ignore[arg-type]  test builder accepts loose kwargs


def test_assembles_valid_bounded_context():
    ctx = ContextAssembler().assemble(
        declared=_research_surface(),
        spec=_spec(),
        approved_capabilities=(SystemCapability.RESEARCH,),
        agent_id="research",
    )
    assert isinstance(ctx, AgentExecutionContext)
    assert ctx.task_id == "t-1"
    assert ctx.approved_capabilities == ("research",)


def test_no_approved_capabilities_allowed():
    ctx = ContextAssembler().assemble(declared=_research_surface(), spec=_spec())
    assert ctx.approved_capabilities == ()


def test_rejects_undeclared_approved_capability():
    with pytest.raises(ContextAssemblyError):
        ContextAssembler().assemble(
            declared=_research_surface(),
            spec=_spec(),
            approved_capabilities=(SystemCapability.CODING_EXECUTION,),  # not declared
        )


def test_rejects_manager_agent_mismatch():
    with pytest.raises(UnknownSystemAgent):
        ContextAssembler().assemble(
            declared=_research_surface(),
            spec=_spec(),
            agent_id="coding",  # wrong owner
        )


def test_rejects_non_exact_surface():
    with pytest.raises(ContextAssemblyError):
        ContextAssembler().assemble(declared="research", spec=_spec())  # type: ignore[arg-type]


def test_rejects_non_exact_spec():
    with pytest.raises(ContextAssemblyError):
        ContextAssembler().assemble(declared=_research_surface(), spec={})  # type: ignore[arg-type]


def test_context_carries_no_executor():
    ctx = ContextAssembler().assemble(declared=_research_surface(), spec=_spec())
    for method in ("execute", "dispatch", "grant", "run"):
        assert not hasattr(ctx, method), f"context must not carry {method}"


def test_context_rejects_unbounded_memory_snippet():
    # Boundedness is enforced by the reusable AgentExecutionContext model at the
    # assembly boundary (fail-closed); an overlong snippet must never reach a built
    # context.
    spec = ContextSpec(
        task_id="t-1",
        step_id="s-1",
        run_id="r-1",
        input="q",
        memory_snippets=("x" * 70_000,),  # exceeds 65,536
    )
    with pytest.raises(Exception):
        ContextAssembler().assemble(declared=_research_surface(), spec=spec)


def test_context_to_dict_valid():
    ctx = ContextAssembler().assemble(declared=_research_surface(), spec=_spec())
    d = ctx.to_dict()
    assert d["task_id"] == "t-1"
    assert d["approved_capabilities"] == ()


def test_assemble_is_side_effect_free_on_declared():
    surface = _research_surface()
    before = surface.declared()
    ContextAssembler().assemble(declared=surface, spec=_spec())
    assert surface.declared() == before


def test_approved_requires_exact_enum_values():
    with pytest.raises(ContextAssemblyError):
        ContextAssembler().assemble(
            declared=_research_surface(),
            spec=_spec(),
            approved_capabilities=("research",),  # type: ignore[list-item]
        )