"""Operations audit event types (Sprint 1.0.6.3).

Event OBJECTS are the existing :class:`agent.runtime.events.RuntimeEvent`
— this layer only adds the operations-specific type constants, so the
whole audit trail stays ONE uniform stream in ``agent_v2_events``.

Append-only contract: approval decisions write one of these events in
the SAME transaction as the durable approval update.
"""

APPROVAL_VIEWED = "APPROVAL_VIEWED"
APPROVAL_APPROVED = "APPROVAL_APPROVED"
APPROVAL_REJECTED = "APPROVAL_REJECTED"
APPROVAL_EXPIRED = "APPROVAL_EXPIRED"

OPERATIONS_EVENT_TYPES = frozenset(
    {
        APPROVAL_VIEWED,
        APPROVAL_APPROVED,
        APPROVAL_REJECTED,
        APPROVAL_EXPIRED,
    }
)
