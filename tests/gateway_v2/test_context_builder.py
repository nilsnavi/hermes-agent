"""TaskContext builder tests (Sprint 1.0.6 §17-19, MUST-HAVE 12)."""

from agent.gateway_v2.context_builder import GatewayRequest, GatewayTaskContextBuilder


def test_builder_preserves_correlation_ids():
    request = GatewayRequest(request_id="req-42", user_id="alice",
                             session_id="sess-9", request_type="chat",
                             goal="find docs", allowed_tools=["search"])
    context = GatewayTaskContextBuilder().build(request)
    assert context.goal == "find docs"
    assert context.allowed_tools == ["search"]
    assert context.metadata["request_id"] == "req-42"
    assert context.metadata["user_id"] == "alice"
    assert context.metadata["session_id"] == "sess-9"
    assert context.metadata["task_type"] == "chat"


def test_builder_scrubs_secrets_from_metadata():
    request = GatewayRequest(
        request_id="req-1", goal="g",
        metadata={"token": "sekrit", "runtime_v2": True, "source": "tg"},
    )
    context = GatewayTaskContextBuilder().build(request)
    assert context.metadata["token"] == "[REDACTED]"
    assert context.metadata["runtime_v2"] is True
    assert context.metadata["source"] == "tg"
    assert "sekrit" not in str(context.metadata)


def test_builder_never_copies_raw_auth_fields():
    """§17 — raw auth/session secrets never enter TaskContext metadata."""
    request = GatewayRequest(
        request_id="req-1", goal="g",
        metadata={"authorization": "Bearer xyz", "api_key": "k-123",
                  "password": "hunter2"},
    )
    context = GatewayTaskContextBuilder().build(request)
    for key in ("authorization", "api_key", "password"):
        assert context.metadata[key] == "[REDACTED]"


def test_constraints_and_risk_forwarded():
    request = GatewayRequest(request_id="req-1", goal="g",
                             constraints=["no deletes"], risk_level="high",
                             approval_required=True)
    context = GatewayTaskContextBuilder().build(request)
    assert context.constraints == ["no deletes"]
    assert context.risk_level == "high"
    assert context.approval_required is True


def test_allowed_tools_override():
    request = GatewayRequest(request_id="req-1", goal="g",
                             allowed_tools=["search", "delete"])
    context = GatewayTaskContextBuilder().build(request, allowed_tools=["search"])
    assert context.allowed_tools == ["search"]


def test_request_id_present_everywhere():
    """MUST-HAVE 12 — legacy and V2 share one correlation id."""
    request = GatewayRequest(request_id="corr-1", goal="g")
    assert request.request_id == "corr-1"
    context = GatewayTaskContextBuilder().build(request)
    assert context.metadata["request_id"] == "corr-1"
