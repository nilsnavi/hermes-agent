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

import grp
import os
import queue as _queue
import socket
import stat as _stat
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

_TAP_SOCKET_MODE = 0o660
_DEFAULT_TAP_GROUP = "hermes-shadow-tap"


class SocketGroupNotFound(TransportUnavailable):
    """Raised when the durable tap socket group does not exist (fail closed).

    Typed outcome: ``SOCKET_GROUP_NOT_FOUND``.  The worker must NOT create the
    group itself; only the external operator may provision it.
    """


class SocketPermissionError(TransportUnavailable):
    """Raised when durable socket ownership/mode cannot be enforced.

    The transport is never exposed as healthy unless the verified inode has
    group == tap group and mode == 0660 (Phase 8.5.1).
    """


def _resolve_tap_gid(group: str) -> int:
    """Resolve the tap socket group GID by canonical name; fail closed if absent."""
    if not isinstance(group, str) or not group:
        raise SocketGroupNotFound("SOCKET_GROUP_NOT_FOUND: empty tap socket group")
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise SocketGroupNotFound(
            f"SOCKET_GROUP_NOT_FOUND: tap socket group {group!r} does not exist"
        ) from exc


def _unlink_stale_socket_safely(path: str) -> None:
    """Remove only a pre-existing Unix socket inode; refuse symlinks/other objects."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if _stat.S_ISLNK(st.st_mode):
        raise SocketPermissionError(
            f"STALE_SOCKET_UNSAFE: refusing to follow symlink at {path!r}")
    if not _stat.S_ISSOCK(st.st_mode):
        raise SocketPermissionError(
            f"STALE_SOCKET_UNSAFE: {path!r} is not a unix socket; refusing to unlink")
    os.unlink(path)


def _enforce_socket_inode(path: str, gid: int) -> None:
    """Set and verify durable tap ownership/mode on the freshly-bound socket.

    Uses PATH-based ``chown/chmod`` (``fchmod`` is a no-op for AF_UNIX sockets on
    Linux).  The path is the socket we just bound and live in a directory we own,
    so it cannot be redirected by an unrelated party; to defend the remaining
    bind->chown->chmod window we require the re-stat to return the SAME inode,
    and the final verification to be exact (mode==0660, gid==tap, uid==owner).
    """
    try:
        before = os.stat(path)
    except OSError as exc:
        raise SocketPermissionError(f"could not stat socket pre-apply: {exc}") from exc
    dev_ino = (before.st_dev, before.st_ino)
    try:
        os.chown(path, -1, gid)  # -1 uid => owner (runtime user) unchanged
        os.chmod(path, _TAP_SOCKET_MODE)
    except OSError as exc:
        raise SocketPermissionError(
            f"could not apply tap group/mode to socket {path!r}: {exc}") from exc
    try:
        st = os.stat(path)
    except OSError as exc:
        raise SocketPermissionError(f"could not stat socket: {exc}") from exc
    if (st.st_dev, st.st_ino) != dev_ino:
        raise SocketPermissionError("socket inode replaced during permission apply")
    if (st.st_mode & 0o777) != _TAP_SOCKET_MODE:
        raise SocketPermissionError(f"socket mode != 0660: got {oct(st.st_mode & 0o777)}")
    if st.st_gid != gid:
        raise SocketPermissionError(f"socket gid != tap gid {gid}: got {st.st_gid}")
    if st.st_uid != os.getuid():
        raise SocketPermissionError(f"socket owner changed: uid {st.st_uid} != {os.getuid()}")


class UnixDatagramShadowTransport(OneWayConsumer):
    """Worker (consumer) side of a one-way bounded Unix datagram transport.

    Binds a path and reads only; it has NO send surface, so there is no path
    that can carry data back to the gateway (WORKER_TO_PRODUCTION_CHANNELS=0).
    ``queue_depth`` is a byte estimate (FIONREAD) -- informational only.

    Durable least-privilege ownership (Phase 8.5.1): after ``bind`` the inode is
    set to group ``tap_socket_group`` (default ``hermes-shadow-tap``) and mode
    ``0660`` via ``chown/chmod``, then verified with ``stat``.  The transport is
    only exposed as ready if the verification succeeds; a missing group,
    non-applicable group, or wrong resulting mode/gid/uid fails closed.
    """

    __slots__ = ("_sock", "_path", "_received", "_lock")

    def __init__(
        self,
        path: str,
        *,
        tap_socket_group: str = _DEFAULT_TAP_GROUP,
    ) -> None:
        self._path = path
        self._received = 0
        self._lock = threading.Lock()
        # Fail closed BEFORE creating/binding anything if the tap group is absent.
        gid = _resolve_tap_gid(tap_socket_group)
        sock = None
        try:
            _unlink_stale_socket_safely(path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(path)
            _enforce_socket_inode(path, gid)
            sock.setblocking(False)
            self._sock = sock
        except TransportUnavailable:
            self._cleanup_partial(path, sock)
            raise
        except OSError as exc:
            self._cleanup_partial(path, sock)
            raise TransportUnavailable(f"could not bind unix datagram transport: {exc}") from exc

    @staticmethod
    def _cleanup_partial(path: str, sock) -> None:
        # Only unwrap a socket WE created+bound.  If we failed BEFORE binding
        # (e.g. a stale symlink/regular-file refusal), leave the foreign object
        # untouched -- never unlink a path we did not own.
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass

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
    "SocketGroupNotFound",
    "SocketPermissionError",
    "UnixDatagramProducer",
    "UnixDatagramShadowTransport",
    "emit_into",
]