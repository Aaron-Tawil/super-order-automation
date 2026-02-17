class BaseAppException(Exception):
    """Base exception for the application."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__(message)
        self.original_error = original_error


class ExtractionError(BaseAppException):
    """Raised when the LLM extraction fails significantly."""

    pass


class ValidationError(BaseAppException):
    """Raised when extracted data fails business rule validation."""

    pass


class SupplierMatchError(BaseAppException):
    """Raised when supplier cannot be identified."""

    pass


class ConfigurationError(BaseAppException):
    """Raised when configuration is missing or invalid."""

    pass
