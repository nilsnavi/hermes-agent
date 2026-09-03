import pytest

from agent.capability_broker.secrets import SecretValue
from agent.integrations.testit.adapter import TestITAdapter
from agent.integrations.testit.client import (
    HttpxTestITTransport,
    TestITClient,
    validate_base_url,
    validate_identifier,
)
from agent.integrations.testit.errors import (
    InvalidTestITConfiguration,
    InvalidTestITIdentifier,
)


class FakeTransport:
    def __init__(self):
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        return {"path": path}


def client(transport=None):
    transport = transport or FakeTransport()

    return TestITClient(
        transport,
        projects_path="/projects",
        testcases_path_template="/projects/{project_id}/testcases",
        testcase_path_template="/testcases/{testcase_id}",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "abc/def",
        r"abc\def",
        "abc?x=1",
        "abc#frag",
        "abc%2fdef",
        "abc\nxyz",
        "",
    ],
)
def test_identifier_rejects_path_and_control_injection(bad):
    with pytest.raises(InvalidTestITIdentifier):
        validate_identifier(bad)


def test_identifier_accepts_bounded_safe_value():
    assert validate_identifier("TC-123:ABC_1") == "TC-123:ABC_1"


@pytest.mark.parametrize(
    "bad",
    [
        "http://testit.example",
        "https://user:pass@testit.example",
        "https://testit.example:8443",
        "https://testit.example/path?q=1",
        "https://testit.example/path#frag",
        "file:///tmp/testit",
    ],
)
def test_base_url_rejects_unsafe_origins(bad):
    with pytest.raises(InvalidTestITConfiguration):
        validate_base_url(bad)


def test_base_url_accepts_https_origin():
    assert (
        validate_base_url("https://testit.example")
        == "https://testit.example"
    )


def test_http_transport_has_no_generic_method_or_header_api():
    transport = HttpxTestITTransport(
        "https://testit.example",
        SecretValue("token"),
    )

    assert not hasattr(transport, "post")
    assert not hasattr(transport, "put")
    assert not hasattr(transport, "patch")
    assert not hasattr(transport, "delete")
    assert not hasattr(transport, "request")
    assert not hasattr(transport, "send")


def test_client_constructs_only_validated_read_paths():
    fake = FakeTransport()
    c = client(fake)

    c.list_projects()
    c.list_testcases("PRJ-1")
    c.get_testcase("TC-42")

    assert fake.paths == [
        "/projects",
        "/projects/PRJ-1/testcases",
        "/testcases/TC-42",
    ]


def test_endpoint_template_requires_exact_placeholder():
    with pytest.raises(InvalidTestITConfiguration):
        TestITClient(
            FakeTransport(),
            projects_path="/projects",
            testcases_path_template="/projects/{project_id}/{other}",
            testcase_path_template="/testcases/{testcase_id}",
        )


def test_adapter_dispatch_is_explicit():
    fake = FakeTransport()
    adapter = TestITAdapter(client(fake))

    adapter.list_projects({})
    adapter.list_testcases({"project_id": "P1"})
    adapter.get_testcase({"testcase_id": "T1"})

    assert fake.paths == [
        "/projects",
        "/projects/P1/testcases",
        "/testcases/T1",
    ]


def test_adapter_rejects_extra_arguments():
    adapter = TestITAdapter(client())

    with pytest.raises(InvalidTestITIdentifier):
        adapter.get_testcase(
            {
                "testcase_id": "T1",
                "url": "https://evil.invalid",
            }
        )


@pytest.mark.parametrize(
    "bad_template",
    [
        "//evil.invalid/projects",
        "/../admin",
        "/api/../admin",
        r"/api\admin",
        "/api/%2fadmin",
        "/api?redirect=https://evil.invalid",
        "/api#fragment",
    ],
)
def test_endpoint_template_rejects_origin_and_path_confusion(bad_template):
    with pytest.raises(InvalidTestITConfiguration):
        TestITClient(
            FakeTransport(),
            projects_path=bad_template,
            testcases_path_template="/projects/{project_id}/testcases",
            testcase_path_template="/testcases/{testcase_id}",
        )
