from typing import Any, Mapping

from agent.capability_broker.audit import InMemoryAuditSink
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
from agent.capability_broker.secrets import SecretValue
from agent.platform_api.auth import Principal
from agent.platform_policy.permissions import (
    PermissionGrant,
    PlatformScope,
)


SECRETS = frozenset({"SYNTH_TESTIT_URL", "SYNTH_TESTIT_TOKEN"})


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    def execute(
        self,
        action: str,
        arguments: Mapping[str, Any],
        secrets: Mapping[str, SecretValue],
    ) -> Any:
        self.calls.append((action, dict(arguments), set(secrets)))
        return {
            "id": "P1",
            "name": "Project",
            "token": "must-be-redacted",
        }


class ExplodingDispatcher:
    def execute(self, action, arguments, secrets):
        raise RuntimeError(
            "upstream exploded Authorization=Bearer plaintext-secret"
        )


def principal():
    return Principal(
        tenant_id="tenant-1",
        principal_id="principal-1",
        user_id="user-1",
        scopes={"integrations.read"},
    )


def context():
    return TrustedCapabilityContext(
        principal=principal(),
        surface=TrustedSurface.DESKTOP,
        request_id="trusted-request-id",
    )


def exact_grant():
    scope = PlatformScope(
        tenant_id="tenant-1",
        principal="principal-1",
        user_id="user-1",
        is_system=False,
    )
    return PermissionGrant(scope, {"integrations.read"})


def secret_backend(name):
    values = {
        "SYNTH_TESTIT_URL": "https://testit.invalid",
        "SYNTH_TESTIT_TOKEN": "synthetic-secret-token",
    }
    return values.get(name)


def broker(
    *,
    enabled=True,
    testit_enabled=True,
    grants=None,
    dispatcher=None,
    audit=None,
):
    return CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=enabled,
            testit_enabled=testit_enabled,
        ),
        grants=(
            frozenset({exact_grant()})
            if grants is None
            else grants
        ),
        secret_backend=secret_backend,
        testit_dispatcher=dispatcher or FakeDispatcher(),
        audit_sink=audit,
    )


def request(operation="testit.projects.read", arguments=None):
    return CapabilityOperationRequest(
        operation=operation,
        arguments=arguments or {},
        # Non-authoritative client correlation: audit must ignore this.
        request_id="spoofed-client-request-id",
    )


def test_default_config_denies_before_dispatch():
    dispatcher = FakeDispatcher()

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(),
        grants=frozenset({exact_grant()}),
        secret_backend=secret_backend,
        testit_dispatcher=dispatcher,
    )

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "CAPABILITY_DISABLED"
    assert dispatcher.calls == []


def test_missing_permission_denies_before_secret_or_dispatch():
    secret_calls = []
    dispatcher = FakeDispatcher()

    def tracking_secret(name):
        secret_calls.append(name)
        return "should-not-be-read"

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=True,
        ),
        grants=frozenset(),
        secret_backend=tracking_secret,
        testit_dispatcher=dispatcher,
    )

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "CAPABILITY_DENIED"
    assert secret_calls == []
    assert dispatcher.calls == []


def test_unknown_operation_denied_before_secret_resolution():
    calls = []

    def tracking_secret(name):
        calls.append(name)
        return "value"

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=True,
        ),
        grants=frozenset({exact_grant()}),
        secret_backend=tracking_secret,
        testit_dispatcher=FakeDispatcher(),
    )

    result = b.execute(
        request("../../execute"),
        context=context(),
    )

    assert result.reason_code == "UNKNOWN_CAPABILITY"
    assert calls == []


def test_successful_operation_resolves_exact_secrets_and_sanitizes():
    dispatcher = FakeDispatcher()
    b = broker(dispatcher=dispatcher)

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.SUCCESS
    assert result.reason_code == "OK"
    assert result.data["token"] == "[REDACTED]"

    assert dispatcher.calls == [
        (
            "list_projects",
            {},
            {"SYNTH_TESTIT_URL", "SYNTH_TESTIT_TOKEN"},
        )
    ]


def test_client_request_id_cannot_spoof_audit_identity():
    audit = InMemoryAuditSink()
    b = broker(audit=audit)

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.SUCCESS
    assert len(audit.events) == 1
    assert audit.events[0].request_id == "trusted-request-id"
    assert audit.events[0].request_id != "spoofed-client-request-id"


def test_upstream_exception_text_never_leaks():
    b = broker(dispatcher=ExplodingDispatcher())

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.ERROR
    assert result.reason_code == "INTEGRATION_UNAVAILABLE"
    assert "plaintext-secret" not in repr(result)
    assert "Authorization" not in repr(result)


def test_testit_gate_denies_before_secret_resolution():
    calls = []

    def tracking_secret(name):
        calls.append(name)
        return "value"

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=False,
        ),
        grants=frozenset({exact_grant()}),
        secret_backend=tracking_secret,
        testit_dispatcher=FakeDispatcher(),
    )

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "CAPABILITY_DISABLED"
    assert calls == []


def test_all_three_read_operations_are_registered():
    registry = build_testit_read_registry(
        required_secret_names=SECRETS
    )

    assert registry.operations() == {
        "testit.projects.read",
        "testit.testcases.read",
        "testit.testcase.read",
    }


def test_registry_contains_no_testit_write_operation():
    registry = build_testit_read_registry(
        required_secret_names=SECRETS
    )

    assert not any(
        ".write" in operation
        or ".create" in operation
        or ".update" in operation
        or ".delete" in operation
        for operation in registry.operations()
    )



def test_missing_secret_maps_to_secret_unavailable():
    def missing_secret(_name):
        return None

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=True,
        ),
        grants=frozenset({exact_grant()}),
        secret_backend=missing_secret,
        testit_dispatcher=FakeDispatcher(),
    )

    result = b.execute(request(), context=context())

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "SECRET_UNAVAILABLE"


def test_invalid_adapter_argument_maps_to_invalid_argument():
    from agent.capability_broker.dispatch import TestITDispatcher
    from agent.integrations.testit.adapter import TestITAdapter
    from agent.integrations.testit.client import TestITClient

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

    b = CapabilityBroker(
        registry=build_testit_read_registry(
            required_secret_names=SECRETS
        ),
        config=CapabilityBrokerConfig(
            enabled=True,
            testit_enabled=True,
        ),
        grants=frozenset({exact_grant()}),
        secret_backend=secret_backend,
        testit_dispatcher=TestITDispatcher(factory),
    )

    result = b.execute(
        request(
            "testit.testcase.read",
            {
                "testcase_id": "../escape",
            },
        ),
        context=context(),
    )

    assert result.result is CapabilityResult.DENIED
    assert result.reason_code == "INVALID_ARGUMENT"
