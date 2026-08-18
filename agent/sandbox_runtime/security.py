"""Security guards (Sprint 1.3.5 §28/§33/§48) — gateway self-control, secrets scan."""

from __future__ import annotations

import os
import re
from typing import List

from .exceptions import (
    GatewaySelfControlBlocked,
    IndirectControlBlocked,
    SandboxPathEscape,
)
from .models import SandboxMutationRequest
from .root import PRODUCTION_PATHS, resolve_sandbox_path

#: Gateway control markers — direct or indirect, any casing.
GATEWAY_CONTROL_RE = re.compile(
    r"(systemctl[^\n;]*restart[^\n;]*hermes-gateway"
    r"|systemctl[^\n;]*hermes-gateway[^\n;]*restart"
    r"|hermes-gateway[^\n;]*restart"
    r"|systemctl[^\n;]*(start|stop|restart|reload)[^\n;]*hermes-gateway\.service)",
    re.IGNORECASE)

#: Indirect execution wrappers around a control command.
INDIRECT_CONTROL_RE = re.compile(
    r"(bash\s+-c|sh\s+-c|eval\s*\(|subprocess[^\n]*systemctl"
    r"|os\.system[^\n]*systemctl|Popen[^\n]*systemctl)",
    re.IGNORECASE)

#: Secret patterns for the security scan (§48) — 0 findings expected.
SECRET_PATTERNS = (
    r"api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"password\s*[=:]\s*['\"][^'\"]{6,}['\"]",
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"Authorization\s*:\s*(Basic|Bearer)\s+\S+",
    r"-----BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY-----",
    r"sk-[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_\-]{30,}",
    r"token\s*[=:]\s*['\"][A-Za-z0-9\-._~+/]{16,}['\"]",
    r"session[_-]?token\s*[=:]\s*\S+",
    r"cookie\s*[=:]\s*['\"][^'\"]{8,}['\"]",
    r"secret[_-]?(key|value)?\s*[=:]\s*['\"][^'\"]{8,}['\"]",
)


class GatewayGuard:
    """§16/§33 — gateway self-control must ALWAYS be blocked
    (direct or indirect)."""

    def check(self, req: SandboxMutationRequest) -> None:
        # 1) service target = production service → BLOCK
        if req.resource_type == "SERVICE":
            from .service import assert_sandbox_service_identity
            try:
                assert_sandbox_service_identity(req.target)
            except Exception as exc:
                raise GatewaySelfControlBlocked(str(exc)) from exc

        # 2) content payloads → scan for gateway control
        content = ""
        for field in ("content", "payload", "data", "command", "script"):
            val = req.arguments.get(field)
            if isinstance(val, str):
                content += val + "\n"
        if not content:
            # path fields can still carry a gateway unit path
            for field in ("path", "target"):
                val = req.arguments.get(field) or req.target
                if isinstance(val, str) and val not in content:
                    content += val + "\n"
        # indirect control (wrapper / script) checked FIRST so a wrapped
        # restart reports INDIRECT, not plain self-control
        if INDIRECT_CONTROL_RE.search(content) or \
                content.lstrip().startswith("#!"):
            if "systemctl" in content.lower() or \
                    "hermes-gateway" in content.lower():
                raise IndirectControlBlocked(
                    "indirect gateway control detected in mutation payload")
        if GATEWAY_CONTROL_RE.search(content):
            raise GatewaySelfControlBlocked(
                "gateway self-control detected in mutation payload")

        # 3) production paths in target/arguments → DENY
        for field in ("path", "target"):
            val = req.arguments.get(field) or req.target
            if not isinstance(val, str) or not val:
                continue
            for prod in PRODUCTION_PATHS:
                if prod in val:
                    raise SandboxPathEscape(
                        f"production path {prod} in mutation argument")
            if val.startswith("/"):
                raise SandboxPathEscape(
                    f"absolute path in mutation argument: {val}")


def scan_for_secrets(paths: List[str]) -> List[str]:
    """Scan files for secret material — returns finding descriptions."""
    findings: List[str] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                findings.append(
                    f"{path}: {pattern} (line {text.count(chr(10), 0, match.start()) + 1})")
    return findings
