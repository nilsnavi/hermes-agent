"""Sprint 1.3.7 core constants — the single narrow production canary contract."""
from __future__ import annotations

import os

#: The ONE production mutation capability introduced in Sprint 1.3.7.
CANARY_CAPABILITY = "HERMES_MANAGED_CANARY_FILE_UPDATE"

#: Canonical production target (expanded at import; realpath checked at runtime).
CANARY_TARGET = os.path.expanduser("~/.hermes/managed/canary/runtime-canary.json")

#: Allowed operation family for the canary capability.
CANARY_OPERATION = "WRITE_FILE"

#: Maximum canary file size (bytes) — schema-controlled, small.
MAX_CANARY_SIZE = 4096

#: Strict schema-controlled keys (no arbitrary keys, no nested structures).
CANARY_SCHEMA_VERSION = 1
CANARY_ALLOWED_KEYS = frozenset({
    "schema_version", "canary_id", "generation", "updated_at",
    "updated_by", "baseline_sha",
})

#: System boundary deny classes (must stay DENY even when canary is active).
CANARY_BOUNDARY_DENY_CLASSES = frozenset({
    "SYSTEM_ACTION", "SERVICE_CONTROL", "NETWORK_CONFIG", "FIREWALL",
    "PACKAGE_MANAGEMENT", "PROCESS_CONTROL", "SCHEDULER", "PROVIDER", "SSH",
})

#: Resource fingerprints that are HARD-DENIED regardless of mode.
#: Specific components (NOT broad substrings like "run"/"etc" that would match
#: the legitimate "runtime-canary.json" basename).
CANARY_DENY_FINGERPRINTS = frozenset({
    "config.yaml", "state.db", ".env", ".ssh", "cron/jobs",
    "scheduler", "inventory.json", "/etc/", "/run/", "/proc/",
    "/sys/", "/dev/", "/boot/", "/root/", "authorized_keys",
})

#: Updated_by marker for canary-managed writes.
UPDATED_BY = "hermes-v2-canary"

#: Central explicit-approval TTL (seconds) and version.
APPROVAL_TTL_SECONDS = 300
APPROVAL_VERSION = 1
