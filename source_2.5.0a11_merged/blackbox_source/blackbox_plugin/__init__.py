"""BBX1 — standalone tamper-evident flight recorder plugin."""
from .client import (
    CLIENT_SCHEMA_VERSION,
    BlackBoxCapabilities,
    BlackBoxClient,
    BlackBoxClientError,
    LocalBlackBoxClient,
    ReceiptVerification,
)
from .errors import (
    BlackBoxError,
    RecorderIntegrityError,
    RecorderSealedError,
    RecordValidationError,
    WitnessUnavailableError,
)
from .models import (
    AppendReceipt,
    Coverage,
    EvidenceEvent,
    ObservationMode,
    RecorderHealth,
    RecorderState,
    VerificationResult,
)
from .migration import (LegacyMigrationError, LegacyRecord, MigrationResult, migrate_legacy_compact_session)
from .recorder import SegmentedBlackBoxRecorder, inspect_session, verify_session
from .service import BlackBoxPlugin

__all__ = [
    "AppendReceipt", "BlackBoxError", "BlackBoxPlugin", "Coverage", "EvidenceEvent",
    "ObservationMode", "RecorderHealth", "RecorderIntegrityError", "RecorderSealedError",
    "RecorderState", "RecordValidationError", "SegmentedBlackBoxRecorder", "VerificationResult",
    "WitnessUnavailableError", "LegacyMigrationError", "LegacyRecord", "MigrationResult",
    "migrate_legacy_compact_session", "inspect_session", "verify_session",
    "CLIENT_SCHEMA_VERSION", "BlackBoxCapabilities", "BlackBoxClient",
    "BlackBoxClientError", "LocalBlackBoxClient", "ReceiptVerification",
]
__version__ = "0.6.0a4"
