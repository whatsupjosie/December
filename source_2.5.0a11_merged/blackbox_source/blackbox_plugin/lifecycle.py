"""Visible coverage state; recorder outages never masquerade as full coverage."""
from __future__ import annotations

from dataclasses import dataclass

from .models import RecorderState


@dataclass(slots=True)
class CoverageWindow:
    state: RecorderState = RecorderState.STARTING
    gap_started_at: str | None = None
    last_error: str | None = None

    def recording_succeeded(self) -> None:
        self.state = RecorderState.HEALTHY
        self.gap_started_at = None
        self.last_error = None

    def recording_failed(self, *, at: str, error: str) -> bool:
        begins = self.gap_started_at is None
        self.gap_started_at = self.gap_started_at or at
        self.last_error = error
        self.state = RecorderState.COVERAGE_GAP
        return begins

    def mark_unavailable(self, error: str) -> None:
        self.last_error = error
        self.state = RecorderState.UNAVAILABLE
