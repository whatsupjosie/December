"""Durable local storage primitives shared by Wallet authority components.

These helpers are intentionally small and boring.  They provide the guarantees
that recovery journals, ceremony records, and portable receipt artifacts rely
on: portable storage identifiers, strict JSON reads, unique atomic-replacement
temporaries, directory durability where the platform supports it, and
cooperating cross-process locks.
"""
from __future__ import annotations

import json
import os
import re
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Type
from uuid import uuid4

from blackbox_plugin.schema import validate_json_value

_STORAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+\-]{0,127}$")
_MAX_STRICT_JSON_BYTES = 64 * 1024 * 1024

_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class DurableIOError(Exception):
    """Raised when a durable local-state operation cannot be proven safe."""


def validate_storage_id(name: str, value: str, *, error_type: Type[Exception] = DurableIOError) -> str:
    if not isinstance(value, str) or not _STORAGE_ID_RE.fullmatch(value):
        raise error_type(f"invalid {name}: {value!r}")
    if value in {".", ".."} or value.endswith((".", " ")):
        raise error_type(f"invalid {name}: {value!r}")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise error_type(f"invalid {name}: reserved path component {value!r}")
    return value


def ensure_within(root: Path, candidate: Path, *, label: str, error_type: Type[Exception] = DurableIOError) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise error_type(f"{label} escapes storage root") from exc
    return candidate_resolved


def _reject_constant(value: str) -> None:
    raise DurableIOError(f"JSON contains non-finite number {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DurableIOError(f"JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except DurableIOError:
        raise
    except Exception as exc:
        raise DurableIOError(f"invalid JSON: {exc}") from exc
    try:
        validate_json_value(value)
    except Exception as exc:
        raise DurableIOError(str(exc)) from exc
    return value


def strict_json_read(path: Path) -> Any:
    """Read one bounded, stable, regular JSON file without following symlinks.

    Authority records frequently live in attacker-interesting directories.  A
    lexical path check is not enough: the final component can be replaced by a
    symlink or special file between checks.  Open the file itself with
    ``O_NOFOLLOW`` where available, verify the descriptor is regular, bound the
    read, and reject records that change while being consumed.
    """
    candidate = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise DurableIOError(f"cannot read {candidate.name}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise DurableIOError(f"cannot read {candidate.name}: not a regular file")
        if before.st_size > _MAX_STRICT_JSON_BYTES:
            raise DurableIOError(
                f"cannot read {candidate.name}: JSON exceeds {_MAX_STRICT_JSON_BYTES} bytes"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_STRICT_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_STRICT_JSON_BYTES:
                raise DurableIOError(
                    f"cannot read {candidate.name}: JSON exceeds {_MAX_STRICT_JSON_BYTES} bytes"
                )
        after = os.fstat(descriptor)
    except DurableIOError:
        raise
    except OSError as exc:
        raise DurableIOError(f"cannot read {candidate.name}: {exc}") from exc
    finally:
        os.close(descriptor)
    stable_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns, before.st_mode,
    )
    stable_after = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
        after.st_ctime_ns, after.st_mode,
    )
    if stable_before != stable_after:
        raise DurableIOError(f"cannot read {candidate.name}: file changed during read")
    try:
        text = b"".join(chunks).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DurableIOError(f"cannot read {candidate.name}: invalid UTF-8") from exc
    return strict_json_loads(text)


def _encoded_json(payload: Mapping[str, Any]) -> bytes:
    validate_json_value(payload)
    return json.dumps(
        dict(payload),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def fsync_directory(path: Path) -> None:
    """Persist directory metadata where the platform exposes directory fsync."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preserve_failed_atomic_temp(temp: Path, target: Path) -> None:
    """Move an abandoned atomic-write temporary into durable recovery storage.

    Wallet's permanent-preservation law applies to evidentiary and authority-adjacent
    write material too. A failed write is preserved for inspection rather than
    being treated as operating residue.  Failure to move it must not hide the original write
    exception; in that case the uniquely named temporary remains in place.
    """
    if not temp.exists():
        return
    recovery_dir = target.parent / ".failed_atomic_writes"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    destination = recovery_dir / (
        f"{target.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.failed"
    )
    os.replace(temp, destination)
    fsync_directory(recovery_dir)
    fsync_directory(target.parent)


def _open_exclusive_private(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags, 0o600)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise DurableIOError("durable write made no forward progress")
        remaining = remaining[written:]


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
    )
    encoded = _encoded_json(payload)
    descriptor: int | None = None
    try:
        descriptor = _open_exclusive_private(temp)
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temp, path)
        fsync_directory(path.parent)
    except BaseException as original_error:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            _preserve_failed_atomic_temp(temp, path)
        except Exception as recovery_error:
            # Preserve the original failure and the uniquely named temporary,
            # but expose that the secondary recovery artifact could not be made.
            if hasattr(original_error, "add_note"):
                original_error.add_note(
                    f"failed atomic temporary remains at {temp}; recovery preservation "
                    f"failed with {type(recovery_error).__name__}: {recovery_error}"
                )
        raise


def exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _encoded_json(payload)
    descriptor = _open_exclusive_private(path)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Cross-process lock for cooperating Wallet writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise DurableIOError(f"lock path is a symlink: {path.name}")
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
