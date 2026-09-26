"""Avatar lane error type. Mirrors the vision lane's VisionError shape but stays local to this
lane's scope -- routes/avatar.py never imports backend.vision.
"""
from contract.enums import ErrorCode


class AvatarError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
