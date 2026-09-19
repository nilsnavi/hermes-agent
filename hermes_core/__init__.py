"""Isolated application-layer foundation for future Hermes runtime migration.

This package intentionally has no imports from the existing runtime.  It defines
contracts and small domain state machines only; adapters are added in a later
migration.
"""

__all__ = ["application", "domain", "ports"]
