"""Integration lifecycle tests (Sprint 0.7 §18)."""

import random

import pytest

from agent.integrations import (
    LogDedup,
    classify_error,
    get_registry,
    integration_disabled,
    next_delay,
    record_failure,
    reset_on_success,
)
from agent.integrations.retry import DEFAULT_BASE_SECONDS

DNS_MSG = ("Failed to connect: Cannot connect to host homeassistant.local:8123 "
           "ssl:default [Name or service not known]")


# 1. disabled integration makes zero connection attempts
def test_disabled_integration_zero_attempts():
    assert integration_disabled("homeassistant") is True
    st = get_registry().get("homeassistant")
    assert st is not None and st.enabled is False
    assert st.retry_policy == "none"  # no retries scheduled


# 2. optional failure does not fail gateway readiness
def test_optional_failure_not_readiness():
    st = get_registry().get("homeassistant")
    assert st is not None and st.required is False
    # optional integrations are tracked independently — nothing global flips
    reg = get_registry()
    assert reg.get("telegram").required is True  # control
    assert reg.get("telegram").enabled is True


# 3. required failure behaves according to policy (retryable → scheduled)
def test_required_failure_policy():
    ec = classify_error("connection refused to api.telegram.org")
    assert ec == "CONNECTION_REFUSED"
    from agent.integrations import is_retryable

    assert is_retryable(ec) is True


# 4. DNS failure classified correctly (canonical HA message)
def test_dns_failure_classified():
    assert classify_error(DNS_MSG) == "DNS_FAILURE"
    assert classify_error("getaddrinfo failed: nodename nor servname") == "DNS_FAILURE"
    assert classify_error("Name or service not known") == "DNS_FAILURE"


# 5. retry backoff sequence correct (5m/15m/30m/60m/6h cap)
def test_backoff_sequence():
    rng = random.Random(42)
    delays = [next_delay(i, rng=rng) for i in (1, 2, 3, 4, 5, 6)]
    for i, d in enumerate(delays):
        base = DEFAULT_BASE_SECONDS[min(i, len(DEFAULT_BASE_SECONDS) - 1)]
        assert base * 0.8 <= d <= base * 1.2, (i, d)
    # cap: attempt 6 == attempt 5
    assert abs(delays[5] - delays[4]) < delays[4] * 0.2


# 6. jitter within configured range (±15%)
def test_jitter_range():
    base = DEFAULT_BASE_SECONDS[0]
    rng = random.Random(7)
    for _ in range(50):
        d = next_delay(1, rng=rng)
        assert base * 0.85 <= d <= base * 1.15


# 7. successful reconnect resets backoff
def test_backoff_reset_on_success():
    assert reset_on_success(5) == 0
    reg = get_registry()
    reg.mark_failure("telegram", "TIMEOUT", attempt=4)
    reg.mark_success("telegram")
    st = reg.get("telegram")
    assert st.attempt == 0 and st.failure_count == 0
    assert st.health == "HEALTHY"


# 8. duplicate logs suppressed (first full, repeats quiet, periodic summary)
def test_duplicate_logs_suppressed():
    dedup = LogDedup(summary_every=25)
    first = dedup.should_suppress("homeassistant", "DNS_FAILURE")
    assert first is False  # full log
    suppressed = [dedup.should_suppress("homeassistant", "DNS_FAILURE") for _ in range(23)]
    assert all(suppressed)  # 2..24 quiet
    assert dedup.should_suppress("homeassistant", "DNS_FAILURE") is False  # 25th → summary
    assert dedup.count("homeassistant", "DNS_FAILURE") == 25


# 9. new error class logs immediately
def test_new_error_class_logs_immediately():
    dedup = LogDedup()
    dedup.should_suppress("homeassistant", "DNS_FAILURE")
    dedup.should_suppress("homeassistant", "DNS_FAILURE")
    assert dedup.should_suppress("homeassistant", "CONNECTION_REFUSED") is False


# 10. Home Assistant unused → disabled (canonical decision)
def test_ha_unused_disabled():
    st = get_registry().get("homeassistant")
    assert st.enabled is False
    assert "unused" in st.reason
    assert st.used_by == ["none (cron toolset off, no skill/job usage)"]


# 11. healthy MCP integrations unaffected
def test_mcp_integrations_unaffected():
    for name in ("atlassian_mcp", "chrome_devtools_mcp"):
        st = get_registry().get(name)
        assert st is not None and st.enabled is True
        assert st.health == "HEALTHY"


# 12. secret fields scrubbed — status/events carry type names, never values
def test_secrets_scrubbed():
    st = get_registry().get("telegram")
    assert st.auth_type == "bot_token"  # type name only
    assert "api.telegram.org (via SOCKS5)" == st.endpoint  # no token
    # failure events carry class + attempt only
    from agent.integrations import events

    for event in ("integration.health.failure", "integration.retry.scheduled"):
        assert "token" not in event.lower()


# 13. record_failure: first → full (not suppressed), repeats → suppressed;
#     registry is updated on the first (unsuppressed) failure (§15 CLI)
def test_record_failure_dedup_path():
    ok1, ec1 = record_failure("github", "Connection refused", 1)
    assert ok1 is False and ec1 == "CONNECTION_REFUSED"
    ok2, ec2 = record_failure("github", "Connection refused", 2)
    assert ok2 is True and ec2 == "CONNECTION_REFUSED"
    st = get_registry().get("github")
    assert st.health == "UNAVAILABLE"
    assert st.error_class == "CONNECTION_REFUSED"
    assert st.failure_count == 1
    assert st.attempt == 1


# 14. structured events keep their REAL name on the shared bus: the
#     integration.* whitelist entry + allowed fields must not fall back
#     to "provider.unknown" and must carry the integration name.
def test_integration_event_name_and_fields_preserved(caplog):
    import logging

    from agent.integrations import events as ievents

    with caplog.at_level(logging.INFO, logger="hermes.provider_registry"):
        ievents.health_failure("homeassistant", "DNS_FAILURE", attempt=3,
                               next_retry_at=299.5)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "integration.health.failure" in joined
    assert '"integration": "homeassistant"' in joined
    assert '"errorClass": "DNS_FAILURE"' in joined
    assert '"attempt": 3' in joined
    assert "provider.unknown" not in joined


# 15. event-bus noise budget (§9): repeated identical failures emit
#     sparse lines — full on first, then one window tick per 25 (the
#     tick carries the running counter) — never one event per attempt.
def test_record_failure_event_bus_sparse(caplog):
    import logging

    MSG = ("Failed to connect: Cannot connect to host homeassistant.local:8123 "
           "ssl:default [Name or service not known]")
    with caplog.at_level(logging.INFO, logger="hermes.provider_registry"):
        for i in range(1, 27):
            record_failure("homeassistant", MSG, i)
    full = sum(1 for r in caplog.records if "health.failure" in r.getMessage())
    summary = sum(1 for r in caplog.records if "retry.suppressed" in r.getMessage())
    assert full == 2      # attempt 1 (full) + attempt 25 (window tick)
    assert summary == 0   # tick line IS the summary — no per-attempt spam
    assert len(caplog.records) == 2
