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
