"""Shared plugin errors with {code, fix} attributes for JSON envelopes."""

from __future__ import annotations


class PluginError(ValueError):
    def __init__(self, message: str, *, code: str = "internal", fix: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


class LibraryError(PluginError):
    def __init__(self, message: str, *, code: str = "library_error", fix: str = "") -> None:
        super().__init__(message, code=code, fix=fix)


class FetchError(LibraryError):
    def __init__(self, message: str, *, code: str = "fetch_failed", fix: str = "") -> None:
        super().__init__(
            message,
            code=code,
            fix=fix or "Retry, or set a local library and asset_mode=offline.",
        )
