"""Integration status CLI (Sprint 0.7 §15) — observability only, no secrets.

Usage:
    python -m agent.integrations.cli status
"""

from __future__ import annotations

import sys


def cmd_status() -> int:
    from agent.integrations import get_registry

    reg = get_registry()
    print(f"{'Integration':<20} {'Enabled':<8} {'Health':<12} {'Last Success':<20} "
          f"{'Last Error':<20} {'Next Retry':<10} {'Required'}")
    for st in sorted(reg.list(), key=lambda s: s.integration):
        print(f"{st.integration:<20} {str(st.enabled):<8} {st.health:<12} "
              f"{(st.last_success or '—')[:19]:<20} {(st.error_class or '—'):<20} "
              f"{'—' if st.next_retry_at is None else 'pending':<10} {str(st.required)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] == "status":
        return cmd_status()
    print(f"unknown command: {args[0]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())