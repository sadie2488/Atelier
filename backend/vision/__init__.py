"""Vision lane: retail garment intake -> saved item with cutout + Lab color.

See backend/vision/CLAUDE.md and the Vision section of contract/DECISIONS.md.
"""
from contract.enums import ErrorCode


class VisionError(Exception):
    """A processing failure the API reports as a contract-shaped error."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
