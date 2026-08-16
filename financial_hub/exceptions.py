class FinancialHubError(Exception):
    """Base exception safe to display in the desktop application."""


class ValidationError(FinancialHubError):
    pass


class ProviderError(FinancialHubError):
    pass


class RateLimitError(ProviderError):
    pass
