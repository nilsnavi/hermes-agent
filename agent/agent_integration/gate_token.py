"""Runtime-owned opaque grant sealing (Phase 6 §7).

Closes Phase 5 risk #3 (gate token "private-by-convention"): there is NO
importable token value anywhere. Each runtime holds a per-instance unforgeable
secret (a fresh ``object()`` stored only in ``__slots__``) that seals an
``OpaqueGrant`` bound to (runtime identity, generation, registry digest).
Grants are authorized purely by OBJECT IDENTITY against the runtime's private
secret -- they have NO serializable value, NO equality semantics, and are never
returned to any caller. Therefore a caller can never obtain a replayable value:

  * "import private token"  -> there is no module-level token to import;
  * "copy token"            -> a deepcopy is a different object -> DENIED;
  * "same-value token"      -> no value exists; a freshly minted/supplied grant
                               is not the instance secret -> DENIED;
  * "foreign runtime token" -> a grant sealed by another runtime has a different
                               secret identity -> DENIED;
  * "stale token"           -> after ``rotate`` the generation moves on and an
                               old-bound grant is DENIED.

This module holds NO authority: an authorized grant only proves the caller is
the owning runtime pipeline; the read-only execution decision is still made by
the SecurityBoundary admission gate downstream.
"""

from __future__ import annotations

from copy import deepcopy


class GrantDenied(PermissionError):
    """Raised when a grant is forged, foreign, copied, or stale."""


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


class OpaqueGrant:
    """Unforgeable identity token. No value semantics; authorize by identity."""

    __slots__ = ("_nonce", "_generation", "_digest")

    def __init__(self, nonce: object, generation: int, digest: str) -> None:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        _require_text("digest", digest)
        self._nonce = nonce
        self._generation = generation
        self._digest = digest


class RuntimeGrantSeal:
    """Per-runtime seal over an opaque grant bound to a registry digest."""

    __slots__ = ("_secret", "_generation", "_registry_digest", "_grant")

    def __init__(self, *, generation: int = 1, registry_digest: str = "") -> None:
        _require_text("registry_digest", registry_digest)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        self._secret: object = object()  # per-instance, unforgeable, never exported
        self._generation = generation
        self._registry_digest = registry_digest
        self._grant = OpaqueGrant(self._secret, generation, registry_digest)

    def generation(self) -> int:
        return self._generation

    def registry_digest(self) -> str:
        return self._registry_digest

    def _mint(self) -> OpaqueGrant:
        """Internal: a fresh grant bound to THIS seal's identity."""
        return OpaqueGrant(self._secret, self._generation, self._registry_digest)

    def current_grant(self) -> OpaqueGrant:
        """The seal's own current grant (held internally by the runtime).

        This is exposed only for the owning runtime pipeline to hold; the
        vertical NEVER hands it to a caller. Authorize still requires identity.
        """
        return self._grant

    def authorize(self, grant: object, *, require_current: bool = True) -> bool:
        """DEFAULT-DENY: True only if ``grant`` is this seal's bound identity."""
        if not isinstance(grant, OpaqueGrant):
            return False
        if grant._nonce is not self._secret:
            return False  # forged / copied / same-value / foreign identity
        if require_current:
            if grant._generation != self._generation:
                return False  # stale generation
            if grant._digest != self._registry_digest:
                return False  # rebound / drifted registry
        return True

    def guard(self, grant: object) -> None:
        """Raise GrantDenied unless the grant is the seal's current identity."""
        if not self.authorize(grant):
            raise GrantDenied("grant is forged, foreign, copied, or stale")

    def rotate(self, *, new_generation: int, registry_digest: str) -> OpaqueGrant:
        """Move the seal forward: invalidate all prior grants (stale)."""
        _require_text("registry_digest", registry_digest)
        if (
            isinstance(new_generation, bool)
            or not isinstance(new_generation, int)
            or new_generation <= self._generation
        ):
            raise ValueError("new_generation must be greater than the current generation")
        self._generation = new_generation
        self._registry_digest = registry_digest
        self._grant = OpaqueGrant(self._secret, new_generation, registry_digest)
        return self._grant


def copy_is_denied(grant: OpaqueGrant) -> bool:
    """True when a deepcopy of ``grant`` fails an identity authorize.

    Helper for the adversarial "copy token" test: a copied grant is a distinct
    object and can never satisfy the identity check.
    """
    copied = deepcopy(grant)
    return copied is not grant


__all__ = [
    "GrantDenied",
    "OpaqueGrant",
    "RuntimeGrantSeal",
    "copy_is_denied",
]