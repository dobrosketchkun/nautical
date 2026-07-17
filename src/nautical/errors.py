"""Public exception hierarchy for embedders and the CLI."""


class NauticalError(RuntimeError):
    """Base class for expected Nautical runtime failures."""


class NotInitializedError(NauticalError):
    """Raised when an operation needs a lexicon database that is not ready."""
