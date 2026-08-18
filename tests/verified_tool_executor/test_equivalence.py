"""Sprint 1.3.2 §28/§29/§49 — equivalence: STATUS_READ (S1-S7) and
SEARCH_READ (P1-P12) must remain behaviorally identical.

Route/tool/output equivalence 100%: for every corpus case, the
verified executor routes to the SAME tool the capability registry
declares and produces the SAME output the existing verified handler
produces (the adapters wrap the exact Sprint 1.0.6 canary handlers —
no behavior change).
"""

import pytest

from agent.capability_router.capabilities import CANONICAL_TOOL_BY_CAPABILITY
from agent.verified_tool_executor.adapter import bind_default_adapters
from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import make_request

# §35 corpus — (phrase, capability, canonical tool) per S1-S7.
# NOTE: "покажи health" is a legacy per-request tool under
# STATUS_RUNTIME (Sprint 1.2.1 §4 heritage) — the canonical registry
# tool for STATUS_RUNTIME is runtime_status, so equivalence is proven
# through the canonical tool.
S_CASES = [
    ("покажи статус Hermes", "STATUS_RUNTIME", "runtime_status"),
    ("статус gateway", "STATUS_GATEWAY", "gateway_status"),
    ("покажи состояние runtime", "STATUS_RUNTIME", "runtime_status"),
    ("покажи health", "STATUS_RUNTIME", "runtime_status"),
    ("работает ли telegram", "STATUS_INTEGRATION", "integration_status"),
    ("статус scheduler", "STATUS_SCHEDULER", "scheduler_status"),
    ("какой сейчас provider", "STATUS_PROVIDER", "provider_status"),
]

# P1-P12 — the Sprint 1.2.4 §12 production allowlist.
P_CASES = [
    ("найди последние ошибки gateway", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("покажи последние события hermes", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("найди ошибки scheduler", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("покажи последние ошибки provider", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("найди ошибки telegram", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("покажи ошибки mcp", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("find recent gateway errors", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("show recent hermes events", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("find scheduler errors", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("show provider errors", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("find telegram errors", "OPERATIONAL_SEARCH",
     "operational_log_search"),
    ("show mcp errors", "OPERATIONAL_SEARCH",
     "operational_log_search"),
]

ALL_EQUIV_CASES = [(*c, "status") for c in S_CASES] + \
    [(*c, "search") for c in P_CASES]


def _default_executor():
    """Executor bound to the DEFAULT migrated adapters (the existing
    canary handlers) for every capability-registry tool, with the
    explicit per-tool argument schemas (§8)."""
    reg = VerifiedToolRegistry()
    bind_default_adapters(reg)
    return VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())


def test_canonical_tool_mapping_matches_capability_registry():
    """Route/tool equivalence: the corpus tool must be the canonical
    capability-registry tool."""
    from agent.capability_router.capabilities import Capability

    for phrase, cap_value, tool in S_CASES + P_CASES:
        cap = Capability(cap_value)
        assert CANONICAL_TOOL_BY_CAPABILITY[cap] == tool, phrase


@pytest.mark.parametrize("phrase,capability,tool,kind", ALL_EQUIV_CASES)
def test_status_read_equivalence(phrase, capability, tool, kind):
    """§28/§29 — S1-S7 + P1-P12 execute via the verified contract and
    produce the SAME output as the existing verified handler."""
    ex = _default_executor()

    req = make_request(
        request_id=f"eq-{kind}-{phrase[:12]}",
        run_id=f"run-{kind}",
        step_id=f"step-{phrase[:12]}",
        capability=capability,
        tool_name=tool,
        idempotency_key=f"idem-{kind}-{phrase}",
        intent="status_read" if kind == "status" else "search_read",
        intent_subtype="runtime" if kind == "status" else "search_read",
        arguments=({"source": "INTEGRATION", "limit": 5}
                   if tool == "operational_log_search" else {}),
        metadata={"goal": phrase},
    )
    res = ex.execute(req)

    # route equivalence: the approved route is V2/SUCCEEDED
    assert res.status is ExecutionStatus.SUCCEEDED, \
        f"{phrase}: {res.error_code} {res.error_class}"
    assert res.tool_name == tool

    # tool/output equivalence: direct handler call gives same output
    from agent.gateway_v2.canary import default_canary_registry

    handler = default_canary_registry().get(tool)
    direct = handler(req.arguments, {"goal": phrase})
    assert res.output == direct, phrase


def test_all_19_corpus_cases_route_v2():
    ex = _default_executor()
    for phrase, capability, tool, kind in ALL_EQUIV_CASES:
        req = make_request(
            request_id=f"r-{phrase[:10]}", run_id="run-all",
            step_id=f"s-{phrase[:10]}", capability=capability,
            tool_name=tool, idempotency_key=f"k-{phrase}",
            intent="status_read" if kind == "status" else "search_read",
            intent_subtype="runtime" if kind == "status" else "search",
            arguments=({"source": "EVENTS", "limit": 3}
                       if tool == "operational_log_search" else {}),
            metadata={"goal": phrase},
        )
        res = ex.execute(req)
        assert res.status is ExecutionStatus.SUCCEEDED, \
            f"{phrase}: {res.error_code}"


def test_unsafe_v2_zero():
    """§49 — unsafe V2 = 0: unsafe intents never produce an execution
    request, and if one somehow reaches the executor it is REJECTED
    (fail closed) — never executed."""
    ex = _default_executor()
    for phrase in ("найди пароль в логах", "удали файл отчёта",
                   "перезапусти gateway", "напомни мне завтра",
                   "отправь сообщение Ивану", "одобри approval"):
        req = make_request(
            request_id=f"neg-{phrase[:10]}", run_id="run-neg",
            step_id=f"s-{phrase[:10]}",
            capability="OPERATIONAL_SEARCH",
            tool_name="operational_log_search",
            idempotency_key=f"k-{phrase}",
            intent="write_action", intent_subtype="write",
            policy_verdict="DENY",  # policy never allows unsafe intents
            arguments={"query": phrase},
            metadata={"goal": phrase},
        )
        res = ex.execute(req)
        # fail closed: never executed
        assert res.status in (
            ExecutionStatus.REJECTED, ExecutionStatus.FAILED), phrase
