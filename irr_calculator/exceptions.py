class IRRCalculatorError(Exception):
    """Base exception safe to display in the desktop application."""


class ValidationError(IRRCalculatorError):
    pass


class ProviderError(IRRCalculatorError):
    pass


class RateLimitError(ProviderError):
    pass
