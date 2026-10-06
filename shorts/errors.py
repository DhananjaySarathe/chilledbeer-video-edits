"""The one error type every command raises: a code, a plain message, and how to fix it."""


class ShortsError(Exception):
    def __init__(self, code: str, message: str, fix: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "fix": self.fix}}
