"""Sprint 1.3.7 §18 — independent verification after adapter SUCCESS.

Adapter SUCCESS is NOT proof: verifier independently re-reads the target and
checks realpath/symlink/owner/mode/size/valid-JSON/schema/content-hash/
generation/baseline_sha.
"""
from __future__ import annotations

import json
import os

from .preflight import gather
from .schema import validate_content_bytes

MAX_EXPECTED_CHUNK = 2 ** 20  # never read absurd files


def verify_after_write(target: str, *, expected_content: bytes, expected_owner: str,
                       expected_mode: int, expected_sha256: str) -> list[str]:
    errors: list[str] = []
    if os.path.islink(target):
        return ["target is symlink"]
    real = os.path.realpath(target)
    if real != target:
        return ["target realpath changed (symlink)"]
    if not os.path.isfile(target):
        return ["target missing after write"]
    st = os.stat(target)
    if st.st_size > MAX_EXPECTED_CHUNK:
        errors.append("target unexpectedly huge")
    try:
        data = open(target, "rb").read()
    except OSError as exc:
        return [f"read failed: {exc}"]
    import hashlib
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        errors.append("content hash mismatch")
    if data != expected_content:
        errors.append("content byte-differs from expected")
    extra = validate_content_bytes(data)
    if extra:
        errors.extend(f"schema: {e}" for e in extra)
    if (st.st_mode & 0o777) != expected_mode:
        errors.append("mode mismatch")
    # owner
    try:
        import pwd
        owner = pwd.getpwuid(st.st_uid).pw_name
        if owner != expected_owner:
            errors.append("owner mismatch")
    except Exception:
        pass
    return errors


def verify_generation(content: bytes, expected_generation: int,
                      expected_baseline: str) -> list[str]:
    errs: list[str] = []
    try:
        d = json.loads(content.decode("utf-8"))
    except Exception:
        return ["not valid JSON"]
    if d.get("generation") != expected_generation:
        errs.append("generation mismatch")
    if d.get("baseline_sha") != expected_baseline:
        errs.append("baseline_sha mismatch")
    return errs
