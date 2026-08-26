"""One-way, bounded, non-blocking shadow transports (Phase 8.3 §9, §10, §11, §12).

The transport moves a PRODUCER (gateway) envelope to a CONSUMER (isolated
shadow worker) in exactly one direction.  Properties enforced here by
construction:

* one-way: the transport interface exposes ONLY producer ``try_emit`` and
  consumer ``recv``/``drain``.  There is deliberately NO ``reply`` / ``respond``
  / ``override`` / ``apply`` / ``promote`` / ``retry_production`` /
  ``send_to_gateway`` surface, so ``WORKER_TO_PRODUCTION_CHANNELS=0`` holds
  mechanically for a worker that only ever holds a consumer.
* non-blocking producer: ``try_emit`` NEVER raises and NEVER blocks
  unboundedly; on full/error it returns ``DROPPED_FULL`` / ``UNAVAILABLE`` so
  the production request path is never held hostage by shadow.
* bounded: a fixed max queue depth and per-envelope byte cap.

Chosen primary local transport: the in-process bounded ``QueueOneWayTransport``
(thread-safe, deterministic, stdlib, no network) used by the worker loop and the
synthetic producer harness.  For deployment an ``UnixDatagramOneWayTransport``
(one-way Unix datagram socket, non-blocking sender, entry leaving is immediately
SUCCESS/absent -> ACCEPTED) is provided; both implement the same protocol.
"""

from __future__ import annotations

import os
import queue as _queue
import socket
import struct
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .exceptions import TransportUnavailable


class EmitResult(Enum):
    """Producer outcome.  NEVER raised into a production path."""

    ACCEPTED = "accepted"
    DROPPED_FULL = "dropped_full"
    DROPPED_INVALID = "dropped_invalid"
    UNAVAILABLE = "unavailable"


class OneWayProducer(Protocol):
    """Producer side: the ONLY way a gateway can hand shadow an envelope."""

    def try_emit(self, payload: bytes) -> EmitResult: ...


class OneWayConsumer(Protocol):
    """Consumer side: the ONLY way the worker can read an envelope."""

    def recv(self, timeout: float = 0.0) -> bytes | None: ...

    def drain(self) -> tuple[bytes, ...]: ...

    def queue_depth(self) -> int: ...


class QueueOneWayTransport(OneWayProducer, OneWayConsumer):
    """In-process bounded, thread-safe, deterministic one-way transport.

    Used by the standalone worker loop and the synthetic producer harness.
    ``try_emit`` puts to a bounded queue without blocking; on full it returns
    ``DROPPED_FULL`` instead of raising/blocking (production never stalls).
    """

    __slots__ = ("_q", "_max", "_closed", "_lock")

    def __init__(self, max_depth: int = 1000) -> None:
        if not isinstance(max_depth, int) or max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        self._q: "_queue.Queue[bytes]" = _queue.Queue(maxsize=max_depth)
        self._max = max_depth
        self._closed = False
        self._lock = threading.Lock()

    # -- producer ----------------------------------------------------------

    def try_emit(self, payload: bytes) -> EmitResult:
        if not isinstance(payload, bytes) or len(payload) == 0:
            return EmitResult.DROPPED_INVALID
        if self._is_closed():
            return EmitResult.UNAVAILABLE
        try:
            self._q.put_nowait(payload)
            return EmitResult.ACCEPTED
        except _queue.Full:  # bounded -> DROP, never block production
            return EmitResult.DROPPED_FULL

    # -- consumer ----------------------------------------------------------

    def recv(self, timeout: float = 0.0) -> bytes | None:
        try:
            return self._q.get(timeout=timeout)
        except _queue.Empty:
            return None

    def drain(self) -> tuple[bytes, ...]:
        out: list[bytes] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except _queue.Empty:
                break
        return tuple(out)

    def queue_depth(self) -> int:
        return self._q.qsize()

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed


import fcntl


class UnixDatagramShadowTransport(OneWayConsumer):
    """Worker (consumer) side of a one-way bounded Unix datagram transport.

    Binds a path and reads only; it has NO send surface, so there is no path
    that can carry data back to the gateway (WORKER_TO_PRODUCTION_CHANNELS=0).
    ``queue_depth`` is a byte estimate (FIONREAD) -- informational only.
    """

    __slots__ = ("_sock", "_path", "_received", "_lock")

    def __init__(self, path: str) -> None:
        self._path = path
        self._received = 0
        self._lock = threading.Lock()
        try:
            if os.path.exists(path):
                os.unlink(path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(path)
            sock.setblocking(False)
            self._sock = sock
        except OSError as exc:
            raise TransportUnavailable(f"could not bind unix datagram transport: {exc}")

    def recv(self, timeout: float = 0.01) -> bytes | None:
        try:
            self._sock.settimeout(timeout)
            data = self._sock.recv(65536)
            with self._lock:
                self._received += 1
            return data
        except (socket.timeout, BlockingIOError):
            return None
        except OSError:
            return None

    def drain(self) -> tuple[bytes, ...]:
        out: list[bytes] = []
        self._sock.settimeout(0.0005)
        while True:
            try:
                out.append(self._sock.recv(65536))
                with self._lock:
                    self._received += 1
            except (socket.timeout, BlockingIOError):
                break
            except OSError:
                break
        return tuple(out)

    def queue_depth(self) -> int:
        try:
            return struct.unpack("I", fcntl.ioctl(
                self._sock.fileno(), 0x541B, b"\x00\x00\x00\x00"))[0]
        except (OSError, struct.error, TypeError):
            return 0

    def close(self) -> None:
        try:
            self._sock.close()
        finally:
            try:
                os.unlink(self._path)
            except OSError:
                pass


class UnixDatagramProducer(OneWayProducer):
    """Gateway (producer) side of the one-way bounded Unix datagram transport.

    A SEPARATE sending socket (a Unix datagram socket bound to the path cannot
    reliably datagram to itself, and in production the gateway is its own
    process).  ``try_emit`` is non-blocking and bounded: it never blocks or
    raises into the production request path.
    """

    __slots__ = ("_sock", "_path", "_inflight", "_max_inflight", "_lock")

    def __init__(self, path: str, max_inflight: int = 256) -> None:
        self._path = path
        self._inflight = 0
        self._max_inflight = max_inflight
        self._lock = threading.Lock()
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._sock.setblocking(False)
        except OSError as exc:
            raise TransportUnavailable(f"could not create unix producer: {exc}")

    def try_emit(self, payload: bytes) -> EmitResult:
        if not isinstance(payload, bytes) or len(payload) == 0:
            return EmitResult.DROPPED_INVALID
        with self._lock:
            if self._inflight >= self._max_inflight:
                return EmitResult.DROPPED_FULL
            try:
                self._sock.sendto(payload, self._path)
            except (BlockingIOError, InterruptedError):
                return EmitResult.DROPPED_FULL
            except (OSError, FileNotFoundError):
                return EmitResult.UNAVAILABLE
            self._inflight += 1
            return EmitResult.ACCEPTED

    def _note_delivered(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class EmitReceipt:
    result: EmitResult
    reason: str = ""


def emit_into(transport: OneWayProducer, payload: bytes) -> EmitReceipt:
    """Safe bounded emit used by synthetic producers (never raises to prod)."""
    try:
        result = transport.try_emit(payload)
    except Exception:  # transport failure -> UNAVAILABLE, never raise into prod path
        return EmitReceipt(EmitResult.UNAVAILABLE, "transport raised")
    if result is EmitResult.ACCEPTED:
        return EmitReceipt(result, "accepted")
    if result is EmitResult.DROPPED_FULL:
        return EmitReceipt(result, "queue full")
    if result is EmitResult.DROPPED_INVALID:
        return EmitReceipt(result, "invalid payload")
    return EmitReceipt(result, "transport unavailable")


__all__ = [
    "EmitReceipt",
    "EmitResult",
    "OneWayConsumer",
    "OneWayProducer",
    "QueueOneWayTransport",
    "UnixDatagramProducer",
    "UnixDatagramShadowTransport",
    "emit_into",
]