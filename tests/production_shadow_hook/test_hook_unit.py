"""Phase 8 hook unit tests: envelope, redaction, modes/flags, transport, try_enqueue."""

import pytest

from agent.production_shadow_hook.envelope import (
    ProductionShadowEnvelope,
    assert_no_forbidden_content,
)
from agent.production_shadow_hook.hook import EnqueueOutcome, ProductionShadowHook
from agent.production_shadow_hook.metrics import ShadowHookMetrics
from agent.production_shadow_hook.modes import HookConfiguration, HookMode
from agent.production_shadow_hook.redaction import sanitize_context
from agent.production_shadow_hook.transport import InMemoryBoundedQueue


def _env(**kw):
    base = dict(
        source_request_id="req-1", tenant_id="acme", user_id="u-1",
        request_kind="monitoring", input_digest="in-1", sanitized_context=("c=1",),
        production_timestamp=1000.0, baseline_version="1.3.6", trace_id="tr-1",
    )
    base.update(kw)
    return ProductionShadowEnvelope(**base)  # type: ignore[arg-type]


# -- envelope -----------------------------------------------------------------
def test_envelope_no_forbidden_fields_and_no_shadow_return_api():
    e = _env()
    assert not hasattr(e, "credentials")
    assert not hasattr(e, "token")
    assert not hasattr(e, "executor")
    assert not hasattr(e, "adapter")
    assert not hasattr(e, "apply")
    assert not hasattr(e, "promote")


def test_envelope_forbidden_content_denied():
    with pytest.raises(ValueError):
        assert_no_forbidden_content(_env(source_request_id="Authorization: Bearer x"))
    assert_no_forbidden_content(_env())


def test_envelope_context_bounded():
    with pytest.raises(ValueError):
        _env(sanitized_context=tuple("x" * 30 for _ in range(20)))


def test_envelope_immutable():
    e = _env()
    with pytest.raises(AttributeError):  # frozen dataclass -> attribute is read-only
        e.tenant_id = "other"  # type: ignore[misc]


# -- redaction (§5) -----------------------------------------------------------
def test_redaction_drops_unknown_and_secret_fields():
    raw = {"request_kind": "monitoring", "task_summary": "health check",
           "user_email": "user@example.com", "password": "hunter2",
           "authorization": "Bearer x", "foo_bad_field": "x", "__secret": "y"}
    out = sanitize_context(raw)
    text = " ".join(out)
    assert "password" not in text and "hunter2" not in text
    assert "authorization" not in text and "Bearer" not in text
    assert "foo_bad_field" not in text
    assert "request_kind=monitoring" in text and "task_summary=health check" in text


def test_redaction_drops_objects_and_none():
    assert sanitize_context({"request_kind": None, "task_summary": object(),
                             "model": "m"}) == ("model=m",)


# -- modes / flags ------------------------------------------------------------
def test_default_off_and_kill_switch_active():
    cfg = HookConfiguration()  # no env overrides set in test env
    assert cfg.enabled is False
    assert cfg.kill_switch is True
    assert cfg.active() is False  # inactive by default


def test_enabled_but_off_mode_inactive():
    cfg = HookConfiguration(enabled=True, kill_switch=False, mode=HookMode.OFF)
    assert cfg.active() is False


def test_kill_switch_blocks_even_when_enabled():
    cfg = HookConfiguration(enabled=True, kill_switch=True, mode=HookMode.CANARY)
    assert cfg.active() is False


def test_canary_active_when_enabled_no_kill():
    cfg = HookConfiguration(enabled=True, kill_switch=False, mode=HookMode.CANARY,
                            sample_rate_per_mille=10)
    assert cfg.active() is True
    assert cfg.sample_per_mille() == 10


# -- transport -----------------------------------------------------------------
def test_bounded_queue_drop_on_full_no_block():
    q = InMemoryBoundedQueue(max_depth=2)
    assert q.try_enqueue(_env()) is True
    assert q.try_enqueue(_env()) is True
    assert q.try_enqueue(_env()) is False  # full -> drop, never blocks
    assert q.depth() == 2
    drained = q.drain(5)
    assert len(drained) == 2
    assert q.depth() == 0


# -- hook ----------------------------------------------------------------------
def _hook(mode=HookMode.CANARY, rate=1000, depth=4, enabled=True, kill=False):
    cfg = HookConfiguration(enabled=enabled, kill_switch=kill, mode=mode,
                            sample_rate_per_mille=rate)
    return ProductionShadowHook(config=cfg, transport=InMemoryBoundedQueue(max_depth=depth),
                                metrics=ShadowHookMetrics())


def test_hook_disabled_returns_unavailable():
    h = _hook(enabled=False)
    assert h.try_enqueue(source_request_id="r", tenant_id="t", user_id="u",
                         request_kind="m", input_digest="i", production_timestamp=1.0,
                         baseline_version="x", raw_context={"request_kind": "m"},
                         trace_id="tr") is EnqueueOutcome.UNAVAILABLE


def test_hook_accepts_and_redacts():
    h = _hook()
    out = h.try_enqueue(source_request_id="r", tenant_id="t", user_id="u",
                        request_kind="m", input_digest="i", production_timestamp=1.0,
                        baseline_version="x",
                        raw_context={"request_kind": "m", "password": "secret",
                                     "task_summary": "ok"},
                        trace_id="tr")
    assert out is EnqueueOutcome.ACCEPTED
    assert h._metrics.get("shadow_hook_enqueued") == 1  # type: ignore[attr-defined]


def test_hook_drops_when_not_sampled():
    h = _hook(rate=0)
    out = h.try_enqueue(source_request_id="r", tenant_id="t", user_id="u",
                        request_kind="m", input_digest="i", production_timestamp=1.0,
                        baseline_version="x", raw_context={"request_kind": "m"},
                        trace_id="tr")
    assert out is EnqueueOutcome.DROPPED
    assert h._metrics.get("shadow_hook_dropped") == 1  # type: ignore[attr-defined]


def test_hook_drops_invalid_envelope():
    h = _hook()
    out = h.try_enqueue(source_request_id="", tenant_id="t", user_id="u",
                        request_kind="m", input_digest="i", production_timestamp=1.0,
                        baseline_version="x", raw_context={"request_kind": "m"},
                        trace_id="tr")
    assert out is EnqueueOutcome.DROPPED
    assert h._metrics.get("shadow_hook_dropped_invalid") == 1  # type: ignore[attr-defined]


def test_hook_drops_when_queue_full_non_blocking():
    cfg = HookConfiguration(enabled=True, kill_switch=False, mode=HookMode.CANARY,
                            sample_rate_per_mille=1000)
    transport = InMemoryBoundedQueue(max_depth=1)
    transport.try_enqueue(_env())  # pre-fill -> queue full
    h = ProductionShadowHook(config=cfg, transport=transport, metrics=ShadowHookMetrics())
    out = h.try_enqueue(source_request_id="r", tenant_id="t", user_id="u",
                        request_kind="m", input_digest="i", production_timestamp=1.0,
                        baseline_version="x", raw_context={"request_kind": "m"},
                        trace_id="tr")
    assert out is EnqueueOutcome.DROPPED
    assert h._metrics.get("shadow_hook_dropped_queue_full") >= 1  # type: ignore[attr-defined]