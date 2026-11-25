"""Strict BBX1 framed record encoding.

Each line is self-framed as::

    BBX1|<urlsafe-base64 strict canonical JSON>|<sha256>

The current serializer is deterministic Python sorted-key JSON with an
I-JSON-compatible input boundary. It is deliberately **not** described as RFC
8785 JCS. A future cross-language verifier may replace this encoder only with
published compatibility vectors and a format-version decision.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import RecordValidationError

ZERO_HASH = "0" * 64
IJSON_SAFE_INTEGER_MAX = (2**53) - 1


def _validate_string(value: str, *, path: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RecordValidationError(f"{path} contains a lone Unicode surrogate") from exc


def validate_json_value(value: Any, *, path: str = "$") -> None:
    """Reject values that cannot round-trip safely across strict JSON readers.

    The accepted domain is intentionally narrower than Python's permissive
    ``json.dumps`` defaults: object keys are strings, floats are finite,
    integers fit the interoperable IEEE-754 exact range, and all strings are
    valid Unicode scalar sequences.
    """

    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _validate_string(value, path=path)
        return
    if isinstance(value, int):
        if abs(value) > IJSON_SAFE_INTEGER_MAX:
            raise RecordValidationError(
                f"{path} integer exceeds I-JSON interoperable range ±{IJSON_SAFE_INTEGER_MAX}"
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecordValidationError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RecordValidationError(f"{path} object key is not a string: {key!r}")
            _validate_string(key, path=f"{path}.<key>")
            validate_json_value(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            validate_json_value(item, path=f"{path}[{index}]")
        return
    raise RecordValidationError(f"{path} contains unsupported JSON value {type(value).__name__}")


def canonical_json(data: Mapping[str, Any]) -> bytes:
    validate_json_value(data)
    try:
        return json.dumps(
            dict(data),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RecordValidationError(f"value cannot be encoded as strict canonical JSON: {exc}") from exc


def hash_body(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(body)).hexdigest()


def encode_record(body: Mapping[str, Any]) -> str:
    raw = canonical_json(body)
    digest = hashlib.sha256(raw).hexdigest()
    framed = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"BBX1|{framed}|{digest}"


def _reject_constant(value: str) -> None:
    raise RecordValidationError(f"record contains non-finite JSON number {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecordValidationError(f"record contains duplicate object key {key!r}")
        result[key] = value
    return result


def decode_record(line: str, *, verify_hash: bool = True) -> dict[str, Any]:
    if not isinstance(line, str) or not line.startswith("BBX1|"):
        raise RecordValidationError("record does not start with BBX1 frame")
    parts = line.rstrip("\r\n").split("|")
    if len(parts) != 3:
        raise RecordValidationError("record frame must have exactly three fields")
    _, framed, supplied_hash = parts
    try:
        padding = "=" * (-len(framed) % 4)
        raw = base64.urlsafe_b64decode((framed + padding).encode("ascii"))
        text = raw.decode("utf-8", errors="strict")
        body = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except RecordValidationError:
        raise
    except Exception as exc:
        raise RecordValidationError(f"record payload cannot be decoded: {exc}") from exc
    if not isinstance(body, dict):
        raise RecordValidationError("record payload must be a JSON object")
    validate_json_value(body)
    expected = hashlib.sha256(raw).hexdigest()
    if verify_hash and supplied_hash != expected:
        raise RecordValidationError("record hash mismatch")
    body["hash"] = supplied_hash
    return body
