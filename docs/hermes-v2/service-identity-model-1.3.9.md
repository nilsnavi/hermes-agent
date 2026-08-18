# Service Identity Model — Sprint 1.3.9

Identity is NOT unit name alone. It combines unit_name, scope, manager,
resolved executable, ExecStart/ExecReload, user/group, MainPID, start time,
cgroup/unit identity, binary identity, working dir, env-file names (names only,
values forbidden).

Results: VERIFIED / PARTIAL / MISMATCH / UNKNOWN. MISMATCH/UNKNOWN → mutation
eligibility DENY. Only VERIFIED supports future eligibility.

Registry is static (authoritative upper bound); runtime discovery may confirm /
raise risk / invalidate / mark mismatch, but never grants authority.
