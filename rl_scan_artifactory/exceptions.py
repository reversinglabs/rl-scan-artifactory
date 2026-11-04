class SpectraAssureExceptions(Exception):
    """A communication class for Spectra Assure exceptions."""

    def __init__(
        self,
        message: str = "",
    ):
        super().__init__(message)


class SpectraAssureInvalidAction(SpectraAssureExceptions):
    """A custom exception class for Spectra Assure Api."""

    def __init__(
        self,
        message: str = "This action is not allowed",
    ):
        super().__init__(message)


class SpectraAssureInvariantError(SpectraAssureExceptions):
    """An internal expectation of this program did not hold.

    These were `assert` statements. An assert vanishes under `python -O`, taking
    the check with it and letting the program continue on a state it had already
    decided was impossible; raising keeps the check in every build.

    Distinct from SpectraAssureInvalidAction on purpose: that one means the user
    asked for something that is not allowed, this one means the program is
    confused about its own state, and the two want different responses.
    """

    def __init__(
        self,
        message: str = "an internal expectation did not hold",
    ):
        super().__init__(message)
