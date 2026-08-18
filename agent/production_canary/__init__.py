"""Sprint 1.3.7 — Narrow Production Change Canary.

The ONLY production mutation capability permitted after the certification
baseline: ``HERMES_MANAGED_CANARY_FILE_UPDATE`` against a single exact
target (``~/.hermes/managed/canary/runtime-canary.json``).

Architecture principle (Sprint 1.3.6 reference): a narrow, exact-identity,
schema-controlled allowlist. No glob targets, no prefix-only checks, no
broad SYSTEM_WRITE / FILE_WRITE_ANY / SYSTEM_CONTROL capability. SYSTEM_CONTROL
must remain OFF throughout.

Strictly additive and standalone (stdlib-only, no imports from org runtime);
wired to production only through an explicit operator-approved narrow canary
gate that is default-OFF.
"""
