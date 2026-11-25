"""Low-level no-clobber custody I/O primitives.

These helpers exist because a preceding ``Path.exists()`` check does not make a
later rename, replace, move, or copy safe against a competing writer.  Custody
publication must fail if a destination appears, must write complete records,
and must preserve the source as transition evidence rather than silently
removing or overwriting bytes.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import TypeVar

from iteration_wallet.durable_io import fsync_directory


_ErrorT = TypeVar("_ErrorT", bound=Exception)
_STORAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HARDLINK_FALLBACK_ERRNOS = {
    errno.EXDEV,
    errno.EPERM,
    errno.EACCES,
    getattr(errno, "EOPNOTSUPP", errno.EPERM),
    getattr(errno, "ENOTSUP", errno.EPERM),
    getattr(errno, "ENOSYS", errno.EPERM),
}


def _raise(error_type: type[_ErrorT], message: str, exc: BaseException | None = None) -> None:
    error = error_type(message)
    if exc is None:
        raise error
    raise error from exc


def validate_transition_id(value: str, *, error_type: type[_ErrorT]) -> str:
    text = str(value or "")
    if not _STORAGE_ID.fullmatch(text):
        _raise(error_type, "custody transition identifier is invalid")
    return text


def write_all(descriptor: int, data: bytes | bytearray | memoryview, *, error_type: type[_ErrorT]) -> int:
    """Write every byte or fail if the OS reports zero/negative progress."""
    view = memoryview(data)
    total = 0
    while view:
        try:
            written = os.write(descriptor, view)
        except OSError as exc:
            _raise(error_type, f"custody write failed after {total} bytes: {exc}", exc)
        if written is None or int(written) <= 0:
            _raise(error_type, "custody write made no forward progress")
        total += int(written)
        view = view[int(written):]
    return total



def ensure_private_directory(
    path: Path,
    *,
    error_type: type[_ErrorT],
    label: str,
) -> Path:
    """Create or verify an owner-only custody directory.

    On POSIX, existing directories are tightened to ``0700`` so a permissive
    process umask cannot expose quarantine or transition evidence to other
    local accounts.  Symlinks and non-directories are always refused.
    """
    if path.is_symlink():
        _raise(error_type, f"{label} cannot be a symlink")
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        _raise(error_type, f"cannot create {label}: {exc}", exc)
    if not path.is_dir():
        _raise(error_type, f"{label} must be a directory")
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            _raise(error_type, f"cannot secure {label}: {exc}", exc)
        if mode & 0o077:
            _raise(error_type, f"{label} is not owner-only")
    return path

def verified_regular_file(path: Path, *, expected_hash: str, expected_size: int, error_type: type[_ErrorT], label: str) -> None:
    if path.is_symlink():
        _raise(error_type, f"{label} cannot be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _raise(error_type, f"cannot open {label} safely: {exc}", exc)
    digest = hashlib.sha256()
    size = 0
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _raise(error_type, f"{label} must be a regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    if size != int(expected_size) or digest.hexdigest() != str(expected_hash):
        _raise(error_type, f"{label} bytes do not match the authorized identity")


def copy_exclusive_exact(
    source: Path,
    destination: Path,
    *,
    expected_hash: str,
    expected_size: int,
    error_type: type[_ErrorT],
    label: str,
) -> None:
    """Copy one exact regular file to a new path using O_EXCL.

    A partial destination is intentionally preserved if the operation fails.
    That path is evidence of the interrupted publication, not disposable trash.
    """
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source, source_flags)
    except OSError as exc:
        _raise(error_type, f"cannot open {label} safely: {exc}", exc)
    destination_fd: int | None = None
    digest = hashlib.sha256()
    copied = 0
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            _raise(error_type, f"{label} must be a regular file")
        if int(info.st_size) != int(expected_size):
            _raise(error_type, f"{label} size changed before publication")
        try:
            destination_fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            _raise(error_type, f"custody destination already exists: {destination}", exc)
        except OSError as exc:
            _raise(error_type, f"cannot create custody destination exclusively: {exc}", exc)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            copied += len(chunk)
            write_all(destination_fd, chunk, error_type=error_type)
        os.fsync(destination_fd)
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        os.close(source_fd)
    if copied != int(expected_size) or digest.hexdigest() != str(expected_hash):
        _raise(
            error_type,
            f"{label} changed during publication; partial destination preserved for reconciliation",
        )
    fsync_directory(destination.parent)


def publish_no_clobber(
    source: Path,
    destination: Path,
    *,
    expected_hash: str,
    expected_size: int,
    error_type: type[_ErrorT],
    label: str,
) -> str:
    """Publish exact bytes to a destination that must not already exist.

    Hard-link publication is atomic and no-clobber on a shared filesystem.  A
    bounded exclusive-copy fallback is used where hard links are unavailable.
    The source remains preserved in either case.
    """
    if destination.is_symlink() or destination.exists():
        _raise(error_type, f"custody destination already exists: {destination}")
    verified_regular_file(
        source,
        expected_hash=expected_hash,
        expected_size=expected_size,
        error_type=error_type,
        label=label,
    )
    try:
        os.link(source, destination, follow_symlinks=False)
        fsync_directory(destination.parent)
        mode = "hardlink"
    except FileExistsError as exc:
        _raise(error_type, f"custody destination appeared during publication: {destination}", exc)
    except OSError as exc:
        if exc.errno not in _HARDLINK_FALLBACK_ERRNOS:
            _raise(error_type, f"custody publication failed: {exc}", exc)
        copy_exclusive_exact(
            source,
            destination,
            expected_hash=expected_hash,
            expected_size=expected_size,
            error_type=error_type,
            label=label,
        )
        mode = "exclusive_copy"
    verified_regular_file(
        destination,
        expected_hash=expected_hash,
        expected_size=expected_size,
        error_type=error_type,
        label=f"published {label}",
    )
    return mode


def relocate_to_transition_evidence(
    source: Path,
    evidence_root: Path,
    *,
    transition_id: str,
    error_type: type[_ErrorT],
    label: str,
) -> Path:
    """Move the original active directory entry into a fresh private evidence dir.

    The operation directory is created atomically, so ``os.rename`` cannot
    overwrite a pre-existing evidence file.  The bytes remain present under the
    new evidence path while the published custody destination remains active.
    """
    safe_id = validate_transition_id(transition_id, error_type=error_type)
    ensure_private_directory(
        evidence_root,
        error_type=error_type,
        label="custody transition evidence root",
    )
    operation_dir = evidence_root / safe_id
    try:
        operation_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        _raise(error_type, f"custody transition evidence already exists: {safe_id}", exc)
    evidence_path = operation_dir / source.name
    try:
        os.rename(source, evidence_path)
    except OSError as exc:
        _raise(
            error_type,
            f"published {label}, but could not preserve the prior active path as transition evidence: {exc}",
            exc,
        )
    fsync_directory(source.parent)
    fsync_directory(operation_dir)
    fsync_directory(evidence_root)
    return evidence_path


def move_custody_no_clobber(
    source: Path,
    destination: Path,
    *,
    evidence_root: Path,
    transition_id: str,
    expected_hash: str,
    expected_size: int,
    error_type: type[_ErrorT],
    label: str,
) -> dict[str, str]:
    mode = publish_no_clobber(
        source,
        destination,
        expected_hash=expected_hash,
        expected_size=expected_size,
        error_type=error_type,
        label=label,
    )
    evidence_path = relocate_to_transition_evidence(
        source,
        evidence_root,
        transition_id=transition_id,
        error_type=error_type,
        label=label,
    )
    return {
        "publication_mode": mode,
        "transition_evidence_path": str(evidence_path),
    }
