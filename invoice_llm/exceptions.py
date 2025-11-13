"""
Custom exceptions for invoice_llm app.
"""


class InvoiceProcessingError(Exception):
    """Base exception for invoice processing errors."""
    pass


class ModelNotFoundError(InvoiceProcessingError):
    """Raised when a requested model is not found or not available."""
    pass


class TextractError(InvoiceProcessingError):
    """Raised when AWS Textract processing fails."""
    pass


class BedrockError(InvoiceProcessingError):
    """Raised when AWS Bedrock processing fails."""
    pass


class ConfigurationError(InvoiceProcessingError):
    """Raised when configuration is invalid or missing."""
    pass


class PDFValidationError(InvoiceProcessingError):
    """Raised when PDF file validation fails."""
    pass
