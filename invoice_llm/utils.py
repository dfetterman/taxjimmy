"""
Utility functions for invoice processing.
"""
import os
import logging
from pathlib import Path
from invoice_llm.exceptions import PDFValidationError

logger = logging.getLogger(__name__)


def validate_pdf_file(file_path):
    """
    Validate that a file exists and is a PDF.
    
    Args:
        file_path: Path to the file to validate
        
    Raises:
        PDFValidationError: If file is invalid
    """
    if not file_path:
        raise PDFValidationError("File path is required")
    
    path = Path(file_path)
    
    if not path.exists():
        raise PDFValidationError(f"File does not exist: {file_path}")
    
    if not path.is_file():
        raise PDFValidationError(f"Path is not a file: {file_path}")
    
    # Check file extension
    if path.suffix.lower() != '.pdf':
        raise PDFValidationError(f"File is not a PDF: {file_path}")
    
    # Check file size (max 50MB for Textract)
    file_size = path.stat().st_size
    max_size = 50 * 1024 * 1024  # 50MB
    if file_size > max_size:
        raise PDFValidationError(f"File is too large: {file_size} bytes (max {max_size} bytes)")
    
    if file_size == 0:
        raise PDFValidationError(f"File is empty: {file_path}")
    
    return True


def read_pdf_file(file_path):
    """
    Read PDF file as bytes.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        bytes: File contents
    """
    validate_pdf_file(file_path)
    
    with open(file_path, 'rb') as f:
        return f.read()


def format_extracted_text(text):
    """
    Format extracted text for better readability.
    
    Args:
        text: Raw extracted text
        
    Returns:
        str: Formatted text
    """
    if not text:
        return ""
    
    # Remove excessive whitespace
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        line = line.strip()
        if line:
            formatted_lines.append(line)
        elif formatted_lines and formatted_lines[-1]:  # Add blank line only if previous line wasn't blank
            formatted_lines.append('')
    
    return '\n'.join(formatted_lines).strip()


def get_file_size_mb(file_path):
    """
    Get file size in megabytes.
    
    Args:
        file_path: Path to the file
        
    Returns:
        float: File size in MB
    """
    return os.path.getsize(file_path) / (1024 * 1024)
