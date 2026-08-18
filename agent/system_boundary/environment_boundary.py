"""Environment / secret boundary (Sprint 1.3.3 §31).

Foundation identifies: full process env inheritance, credential file
access, private key access, token store, secret-bearing environment
injection. SECRET_RESOURCE → risk floor increases. Environment values
are never logged.
"""

from typing import Dict, List, Optional

from .models import (
    OperationClass,
    ResourceClass,
    block_decision,
    pass_decision,
)

#: env var names that carry secrets
_SECRET_ENV_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
    "ACCESS_KEY", "PRIVATE_KEY", "CREDENTIAL", "AUTH", "KEY=",
    "PWD=", "LOGIN", "CLIENT_SECRET", "BEARER",
)


def env_inherits_secrets(environ: Optional[Dict[str, str]]) -> bool:
    """True when the environment contains secret-bearing variables."""
    if not environ:
        return False
    for name in environ:
        up = name.upper()
        for marker in _SECRET_ENV_MARKERS:
            if marker in up:
                return True
    return False


def classify_env_injection(arguments: Dict[str, str]) -> bool:
    """True when an 'env VAR=secret cmd' style injection carries
    secret-looking names."""
    for key, value in (arguments or {}).items():
        up = str(key).upper()
        for marker in _SECRET_ENV_MARKERS:
            if marker in up:
                return True
    return False


class EnvironmentBoundary:
    """Fail-closed environment/secret boundary."""

    def evaluate(self, operation: str,
                 environ: Optional[Dict[str, str]] = None,
                 target_resource: Optional[str] = None,
                 env_arguments: Optional[Dict[str, str]] = None) -> object:
        secret_env = env_inherits_secrets(environ)
        secret_inject = classify_env_injection(env_arguments)
        is_secret_resource = target_resource == \
            ResourceClass.SECRET_RESOURCE.value

        if operation == OperationClass.SECRET_ACCESS.value:
            return block_decision("SECRET_RESOURCE_DETECTED")

        # SECRET_RESOURCE → risk floor increases; still passable for
        # reads (policy engine decides), but never silently logged
        if is_secret_resource or secret_env or secret_inject:
            decision = pass_decision(
                "SBL_OK",
                resource_class=ResourceClass.SECRET_RESOURCE.value,
                risk_floor="SYSTEM", risk_after="SYSTEM")
            return decision
        return pass_decision("SBL_OK")


__all__ = [
    "EnvironmentBoundary",
    "env_inherits_secrets",
    "classify_env_injection",
]
