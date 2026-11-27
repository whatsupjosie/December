"""Small, portable helpers for writing PubPartner's memory files so a crash or power cut loses as little as possible.

Two problems these solve, both found by cutting writes short on purpose:

* A row appended to a log was never flushed to disk, so a power cut could lose it, and a cut in the
  middle of a row left a last line with no newline. The NEXT append was then glued onto that torn
  line, so one good row was lost with it. ``append_row`` flushes to disk and, if the file does not
  end in a newline, starts the new row on a fresh line.
* A file written and then renamed into place (the exact-words files) was never flushed, so after a
  power cut the name could exist with nothing inside. ``write_bytes_durable`` flushes first.

Flushing is always done through the handle that did the writing, which is the only way Windows allows.
Nothing here deletes or rewrites existing rows.
"""
from __future__ import annotations

import os
from pathlib import Path


def _ends_without_newline(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        with path.open("rb") as handle:
            handle.seek(size - 1)
            return handle.read(1) != b"\n"
    except FileNotFoundError:
        return False


def append_row(path: Path | str, row: str) -> None:
    """Append one text row (already ending in a newline) and flush it to disk."""
    path = Path(path)
    prefix = "\n" if _ends_without_newline(path) else ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + row)
        handle.flush()
        os.fsync(handle.fileno())


def tail_lines(path: Path | str, count: int, *, block_size: int = 65536) -> list[str]:
    """The last ``count`` non-blank rows of a text log, read from the end so cost does not grow with the file.

    Rows end at newline only (not at U+2028 and friends, which JSON leaves unescaped). A last row that was
    cut short by a crash is returned like any other; bytes that are not valid UTF-8 are replaced, never raised.
    """
    path = Path(path)
    count = max(1, int(count))
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        data = b""
        while True:
            pieces = data.split(b"\n")
            if position > 0:
                pieces = pieces[1:]  # the first piece starts mid-row, so it cannot be trusted yet
            usable = [piece for piece in pieces if piece.strip()]
            if len(usable) >= count or position == 0:
                break
            step = min(block_size, position)
            position -= step
            handle.seek(position)
            data = handle.read(step) + data
    rows = [piece.decode("utf-8", errors="replace") for piece in usable]
    return rows[-count:]


def write_bytes_durable(path: Path | str, data: bytes) -> None:
    """Write ``data`` to ``path`` and flush it to disk before returning."""
    with Path(path).open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def write_text_durable(path: Path | str, text: str) -> None:
    write_bytes_durable(path, text.encode("utf-8"))


__all__ = ["append_row", "tail_lines", "write_bytes_durable", "write_text_durable"]
