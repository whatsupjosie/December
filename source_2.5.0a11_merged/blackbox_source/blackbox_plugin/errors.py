"""BlackBox plugin exceptions."""

class BlackBoxError(RuntimeError):
    """Base error for expected BlackBox failures."""


class RecordValidationError(BlackBoxError):
    """A submitted record is malformed or exceeds the safe envelope."""


class RecorderIntegrityError(BlackBoxError):
    """The existing record cannot be trusted enough to append."""


class RecorderSealedError(BlackBoxError):
    """A sealed session cannot accept new records."""


class WitnessUnavailableError(BlackBoxError):
    """A host required witness acknowledgement but no recorder was available."""
