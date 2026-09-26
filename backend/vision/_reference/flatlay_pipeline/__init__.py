from contract.enums import ErrorCode


class PipelineError(Exception):
    """A processing failure the API reports as a contract error."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
