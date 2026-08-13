"""Shared fixtures for intent_router tests (Sprint 1.1)."""

import pytest

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    IntentRisk,
    IntentType,
    RequestIntentFeatures,
)
from agent.intent_router.router import IntentRouter


@pytest.fixture
def router_healthy():
    """Router with canary+shadow enabled and HEALTHY runtime."""
    return IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=lambda: {"status": "healthy"},
    )


@pytest.fixture
def router_off():
    """Router with everything off (defaults)."""
    return IntentRouter(
        flags={"enabled": False, "mode": "off",
               "canary": False, "shadow": False},
        health_provider=lambda: {"status": "healthy"},
    )


def features(text, request_id="t", **kw):
    """Features from a text with optional overrides."""
    return features_from_text(text, request_id=request_id, **kw)


def run(router, text, **kw):
    """Observe one text and return the decision."""
    return router.observe(features(text, **kw))


@pytest.fixture
def internal():
    """Internal allowlisted request marker."""
    return {"internal": True}
