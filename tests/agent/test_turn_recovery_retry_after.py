from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from agent.turn_recovery import compute_error_backoff


class _Agent:
    def __init__(self):
        self.buffered = []
        self.emitted = []

    def _buffer_status(self, message):
        self.buffered.append(message)

    def _emit_status(self, message):
        self.emitted.append(message)

    def _client_log_context(self):
        return "test"


class _HTTPError(Exception):
    def __init__(self, status_code, headers=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


def _compute(
    error,
    *,
    monkeypatch,
    is_rate_limited=False,
    is_zai_coding_overload=False,
    retry_count=1,
):
    # Deterministic fallback so each test can prove whether Retry-After won.
    monkeypatch.setattr(
        "agent.retry_utils.jittered_backoff",
        lambda *args, **kwargs: 7.0,
    )

    return compute_error_backoff(
        _Agent(),
        error,
        retry_count=retry_count,
        max_retries=3,
        is_rate_limited=is_rate_limited,
        is_zai_coding_overload=is_zai_coding_overload,
        base_url="https://example.invalid/v1",
        model="test/model",
    )


@pytest.mark.parametrize(
    ("status_code", "retry_after"),
    [
        (502, "15"),
        (503, "30"),
    ],
)
def test_transient_5xx_honors_retry_after(
    monkeypatch,
    status_code,
    retry_after,
):
    wait = _compute(
        _HTTPError(status_code, {"Retry-After": retry_after}),
        monkeypatch=monkeypatch,
    )

    assert wait == float(retry_after)


def test_504_honors_http_date_retry_after(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(seconds=30)

    wait = _compute(
        _HTTPError(
            504,
            {"Retry-After": format_datetime(future, usegmt=True)},
        ),
        monkeypatch=monkeypatch,
    )

    # Parsing and function execution consume a small amount of wall-clock time.
    assert 25.0 <= wait <= 30.0


def test_transient_5xx_without_retry_after_uses_jitter(monkeypatch):
    wait = _compute(
        _HTTPError(502),
        monkeypatch=monkeypatch,
    )

    assert wait == 7.0


def test_retry_after_is_capped_at_600_seconds(monkeypatch):
    wait = _compute(
        _HTTPError(503, {"Retry-After": "9999"}),
        monkeypatch=monkeypatch,
    )

    assert wait == 600.0


def test_rate_limit_retry_after_preserves_existing_behavior(monkeypatch):
    wait = _compute(
        _HTTPError(429, {"retry-after": "45"}),
        monkeypatch=monkeypatch,
        is_rate_limited=True,
    )

    assert wait == 45.0


def test_retry_after_zero_suppresses_adaptive_backoff(monkeypatch):
    called = {"adaptive": False}

    def _adaptive(*args, **kwargs):
        called["adaptive"] = True
        return 99.0, "unexpected"

    monkeypatch.setattr(
        "agent.retry_utils.adaptive_rate_limit_backoff",
        _adaptive,
    )

    wait = _compute(
        _HTTPError(429, {"Retry-After": "0"}),
        monkeypatch=monkeypatch,
        is_rate_limited=True,
    )

    assert wait == 0.0
    assert called["adaptive"] is False
