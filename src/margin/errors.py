class TransientModelError(Exception):
    """A model-call failure worth retrying (overload, rate limit, dropped connection)."""


class SimulatedCrash(Exception):
    """Raised by tests and the resume demo to emulate a killed process after a checkpoint."""
