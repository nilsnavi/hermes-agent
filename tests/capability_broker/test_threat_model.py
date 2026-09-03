"""Phase 9.1.1 Capability Broker threat-model certification.

T1  request identity spoofing
T2  tenant/grant escalation
T3  unknown operation injection
T4  secret-name exfiltration
T5  URL/origin injection
T6  mutating HTTP surface
T7  argument/path traversal
T8  upstream exception leakage
T9  audit secret leakage
T10 disabled-by-default bypass
"""

from dataclasses import fields

import pytest

from agent.capability_broker.audit import (
    CapabilityAuditEvent,
    InMemoryAuditSink,
)
from agent.capability_broker.broker import CapabilityBroker
from agent.capability_broker.config import CapabilityBrokerConfig
from agent.capability_broker.context import (
    TrustedCapabilityContext,
    TrustedSurface,
)
from agent.capability_broker.models import (
    CapabilityOperationRequest,
    CapabilityResult,
)
from agent.capability_broker.registry_factory import (
    build_testit_read_registry,
)
from agent.capability_broker.secrets import (
    ScopedSecretResolver,
    SecretAccessDenied,
    SecretValue,
)
from agent.integrations.testit.client import (
    HttpxTestITTransport,
    TestITClient,
)
from agent.integrations.testit.errors import InvalidTestITConfiguration
from agent.platform_api.auth import Principal
from agent.platform_policy.permissions import (
    PermissionGrant,
    PlatformScope,
)


SECRETS = frozenset(
    {
        "SYNTH_TESTIT_URL",
        "SYNTH_TESTIT_TOKEN",
    }
)


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    def execute(self, action, arguments, secrets):
        self.calls.append(
            (
                action,
                dict(arguments),
                frozenset(secrets),
            )
        )
        return {
            "ok": True,
            "TOKEN": "synthetic-token-must-not-cross-boundary",
        }


class ExplodingDispatcher:
    def execute(self, action, arguments, secrets):
        raise RuntimeError(
            "Authorization: Bearer SUPER_SECRET_PLAINTEXT"
        )


def principal(
    tenant="tenant-1",
    principal_id="principal-1",
):
    return Principal(
        tenant_id=tenant,
        principal_id=principal_id,
        user_id=principal_id,
        scopes={"integrations.read"},
    )


def context(
    tenant="tenant-1",
    principal_id="principal-1",
):
    return TrustedCapabilityContext(
        principal=principal(
            tenant=tenant,
            principal_id=principal_id,
        ),
        surface=TrustedSurface.DESKTOP,
        request_id="trusted-correlation",
    )


def grant(
    tenant="tenant-1",
    principal_id="principal-1",
):
    return PermissionGrant(
        PlatformScope(
            tenant_id=tenant,
            principal=principal_id,
            user_id=principal_id,
            is_system=False,
        ),
        {"integrations.read"},
    )


def secret_backend(name):
    return {
        "SYNTH_TESTIT_URL": "https://testit.invalid",
        "SYNTH_TESTIT_TOKEN": "synthetic-token",
    }.get(name)


def broker(
    *,
    config=None,
    grants=None,
    dispatcher=None,
    audit_sink=None,
):
    return CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS,
        ),
        config=config
        or CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=True,
        ),
        grants=(
            frozenset({grant()})
            if grants is None
            else grants
        ),
        secret_backend=secret_backend,
        testit_dispatcher=dispatcher or FakeDispatcher(),
        audit_sink=audit_sink,
    )


# T1
def test_t1_request_cannot_supply_identity_or_authority():
    names = {
        field.name
        for field in fields(CapabilityOperationRequest)
    }

    assert names.isdisjoint(
        {
            "caller",
            "principal",
            "tenant",
            "tenant_id",
            "permissions",
            "grant",
            "grants",
            "scopes",
            "authority",
        }
    )


# T2
def test_t2_cross_tenant_grant_cannot_authorize():
    b = broker(
        grants=frozenset(
            {
                grant(
                    tenant="tenant-2",
                    principal_id="principal-1",
                )
            }
        )
    )

    result = b.execute(
        CapabilityOperationRequest(
            "testit.projects.read"
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "CAPABILITY_DENIED"


# T3
def test_t3_unknown_operation_cannot_reach_dispatch():
    dispatcher = FakeDispatcher()
    b = broker(dispatcher=dispatcher)

    result = b.execute(
        CapabilityOperationRequest(
            "testit.__class__.__mro__"
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "UNKNOWN_CAPABILITY"
    assert dispatcher.calls == []


# T4
def test_t4_unscoped_secret_name_is_denied():
    resolver = ScopedSecretResolver(
        frozenset({"SYNTH_TESTIT_TOKEN"}),
        backend=lambda name: "value",
    )

    with pytest.raises(SecretAccessDenied):
        resolver.resolve("OPENAI_API_KEY")


# T5
@pytest.mark.parametrize(
    "bad",
    [
        "//evil.invalid/x",
        "/../admin",
        r"/api\admin",
        "/api/%2fadmin",
    ],
)
def test_t5_endpoint_template_cannot_escape_origin(bad):
    class FakeTransport:
        def get(self, path):
            return {}

    with pytest.raises(InvalidTestITConfiguration):
        TestITClient(
            FakeTransport(),
            projects_path=bad,
            testcases_path_template="/projects/{project_id}/testcases",
            testcase_path_template="/testcases/{testcase_id}",
        )


# T6
def test_t6_http_transport_exposes_no_mutation_or_generic_request_surface():
    transport = HttpxTestITTransport(
        "https://testit.invalid",
        SecretValue("synthetic-token"),
    )

    forbidden = {
        "post",
        "put",
        "patch",
        "delete",
        "request",
        "send",
    }

    assert all(
        not hasattr(transport, name)
        for name in forbidden
    )


# T7
def test_t7_request_path_argument_cannot_traverse():
    from agent.capability_broker.dispatch import TestITDispatcher
    from agent.integrations.testit.adapter import TestITAdapter

    class FakeTransport:
        def get(self, path):
            return {"path": path}

    def factory(_secrets):
        return TestITAdapter(
            TestITClient(
                FakeTransport(),
                projects_path="/projects",
                testcases_path_template="/projects/{project_id}/testcases",
                testcase_path_template="/testcases/{testcase_id}",
            )
        )

    b = broker(
        dispatcher=TestITDispatcher(factory),
    )

    result = b.execute(
        CapabilityOperationRequest(
            operation="testit.testcase.read",
            arguments={
                "testcase_id": "../../admin",
            },
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "INVALID_ARGUMENT"


# T8
def test_t8_raw_upstream_exception_never_crosses_boundary():
    b = broker(
        dispatcher=ExplodingDispatcher()
    )

    result = b.execute(
        CapabilityOperationRequest(
            "testit.projects.read"
        ),
        context=context(),
    )

    rendered = repr(result)

    assert result.result is CapabilityResult.ERROR
    assert "SUPER_SECRET_PLAINTEXT" not in rendered
    assert "Authorization" not in rendered


# T9
def test_t9_audit_schema_and_event_do_not_contain_secrets_or_arguments():
    audit = InMemoryAuditSink()
    b = broker(audit_sink=audit)

    result = b.execute(
        CapabilityOperationRequest(
            "testit.projects.read",
            request_id="untrusted-client-id",
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.SUCCESS
    assert len(audit.events) == 1

    event = audit.events[0]

    assert event.request_id == "trusted-correlation"

    names = {
        field.name
        for field in fields(CapabilityAuditEvent)
    }

    assert names.isdisjoint(
        {
            "arguments",
            "token",
            "secret",
            "headers",
            "authorization",
            "response",
            "exception",
        }
    )

    rendered = repr(event)
    assert "synthetic-token" not in rendered


# T10
def test_t10_default_configuration_cannot_dispatch_or_resolve_secret():
    dispatcher = FakeDispatcher()
    secret_reads = []

    def tracking_backend(name):
        secret_reads.append(name)
        return "value"

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS,
        ),
        config=CapabilityBrokerConfig(),
        grants=frozenset({grant()}),
        secret_backend=tracking_backend,
        testit_dispatcher=dispatcher,
    )

    result = b.execute(
        CapabilityOperationRequest(
            "testit.projects.read"
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "CAPABILITY_DISABLED"
    assert secret_reads == []
    assert dispatcher.calls == []
