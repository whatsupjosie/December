"""Standalone plugin facade for hosts that want a BlackBox witness."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .models import AppendReceipt, Coverage, EvidenceEvent, ObservationMode
from .recorder import SegmentedBlackBoxRecorder
from .views import closed_summary, known_record_report, object_history


class BlackBoxPlugin:
    def __init__(self, storage_root: Path | str, session_id: str, **recorder_options: Any) -> None:
        self.recorder = SegmentedBlackBoxRecorder(storage_root, session_id, **recorder_options)

    @property
    def session_dir(self) -> Path:
        return self.recorder.session_dir

    def append_event(self, event: EvidenceEvent, *, expected_previous_hash: str | None = None) -> AppendReceipt:
        return self.recorder.append(event, expected_previous_hash=expected_previous_hash)

    def record(
        self,
        *,
        event_type: str,
        source: str,
        actor: str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
        operation_id: str | None = None,
        source_sequence: int | None = None,
        observation_mode: ObservationMode = ObservationMode.DIRECT,
        coverage: Coverage = Coverage.FULL,
        channel: str = "GEN",
        event_code: str = "OBS",
    ) -> AppendReceipt:
        return self.append_event(
            EvidenceEvent(
                event_type=event_type,
                source=source,
                actor=actor,
                subject_id=subject_id,
                payload=dict(payload or {}),
                operation_id=operation_id,
                source_sequence=source_sequence,
                observation_mode=observation_mode,
                coverage=coverage,
                session_id=self.recorder.session_id,
                channel=channel,
                event_code=event_code,
            )
        )

    def verify(self) -> dict[str, Any]:
        return self.recorder.verify().to_dict()

    def health(self) -> dict[str, Any]:
        return self.recorder.health().to_dict()

    def seal(self, reason: str = "manual") -> Path:
        return self.recorder.seal(reason)

    def closed_summary(self) -> dict[str, Any]:
        records = self.recorder.iter_records()
        return closed_summary(records, self.verify())

    def object_history(self, subject_id: str) -> dict[str, Any]:
        return object_history(self.recorder.iter_records(), subject_id)

    def known_record_report(self) -> str:
        return known_record_report(self.recorder.iter_records(), self.verify())
