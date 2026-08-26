"""Phase 8.3 -- Isolated Shadow Worker & Tap Contract (read-only, no prod effect).

A standalone, independently executable worker that consumes a one-way bounded
``ProductionShadowEnvelopeV1`` from a production gateway and drives exactly ONE
read-only shadow run (reusing ``agent.platform_shadow`` -- a single read side,
never a second execution engine).  The worker has no reply/override path, no
production authority, no memory writes in worker mode, and no network access by
default (``NETWORK_READ_ONLY_DEFAULT=DENIED``).

Live activation is OFF in Phase 8.3 (no live hook, no production deployment).
"""

from .audit import (
    WORKER_AUDIT_CHAIN_ORDER,
    WorkerAuditEvent,
    WorkerAuditKind,
    WorkerAuditStore,
)
from .config import DEFAULT_CONFIG, WorkerConfig
from .envelope import (
    DEFAULT_MAX_ENVELOPE_BYTES,
    ENVELOPE_SCHEMA_VERSION,
    EnvelopeParseResult,
    ProductionShadowEnvelopeV1,
    parse_envelope,
)
from .exceptions import (
    EnvelopeValidationError,
    TransportUnavailable,
    UnknownEnvelopeSchema,
    WorkerConfigError,
    WorkerError,
    WorkerKillSwitchEngaged,
)
from .health import HealthSnapshot, WorkerHealth
from .lifecycle import (
    WorkerLifecycle,
    WorkerLifecycleError,
    WorkerLifecycleState,
)
from .metrics import (
    WORKER_METRIC_NAMES,
    MetricsSummary,
    WorkerMetricError,
    WorkerMetrics,
)
from .transport import (
    EmitReceipt,
    EmitResult,
    OneWayConsumer,
    OneWayProducer,
    QueueOneWayTransport,
    UnixDatagramProducer,
    UnixDatagramShadowTransport,
    emit_into,
)
from .worker import ShadowRunner, ShadowWorker, WorkerOutcome, WorkerStatus

#: Mechanical isolation marker (Phase 8.3 §10, §28).
WORKER_TO_PRODUCTION_CHANNELS = 0
GATEWAY_RUNTIME_COUPLING = 0
SECOND_EXECUTION_ENGINE = False
SHADOW_MEMORY_WRITES = False  # Phase 8.3 default OFF
NETWORK_READ_ONLY_DEFAULT = False  # denied by default
LIVE_ACTIVATION = False

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_MAX_ENVELOPE_BYTES",
    "ENVELOPE_SCHEMA_VERSION",
    "EmitReceipt",
    "EmitResult",
    "EnvelopeParseResult",
    "GATEWAY_RUNTIME_COUPLING",
    "HealthSnapshot",
    "LIVE_ACTIVATION",
    "MetricsSummary",
    "NETWORK_READ_ONLY_DEFAULT",
    "OneWayConsumer",
    "OneWayProducer",
    "ProductionShadowEnvelopeV1",
    "QueueOneWayTransport",
    "SECOND_EXECUTION_ENGINE",
    "SHADOW_MEMORY_WRITES",
    "ShadowRunner",
    "ShadowWorker",
    "TransportUnavailable",
    "UnixDatagramProducer",
    "UnixDatagramShadowTransport",
    "WORKER_AUDIT_CHAIN_ORDER",
    "WORKER_METRIC_NAMES",
    "WorkerAuditEvent",
    "WorkerAuditKind",
    "WorkerAuditStore",
    "WorkerConfig",
    "WorkerConfigError",
    "WorkerError",
    "WorkerHealth",
    "WorkerLifecycle",
    "WorkerLifecycleError",
    "WorkerLifecycleState",
    "WorkerMetricError",
    "WorkerMetrics",
    "WorkerOutcome",
    "WorkerStatus",
    "WorkerKillSwitchEngaged",
    "UnknownEnvelopeSchema",
    "emit_into",
    "parse_envelope",
]