from __future__ import annotations


class FundingTerminalError(Exception):
    """Base application exception with a user-safe message."""


class ImportValidationError(FundingTerminalError):
    pass


class BinanceUnavailableError(FundingTerminalError):
    pass


class DatabaseUnavailableError(FundingTerminalError):
    pass


class InvalidSymbolError(FundingTerminalError):
    pass


class SettingsValidationError(FundingTerminalError):
    pass

