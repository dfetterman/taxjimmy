"""
Service classes for processing invoice data from OCR.
"""
import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, Any, Optional
from django.utils import timezone

from taxright.models import Invoice, InvoiceLineItem

logger = logging.getLogger(__name__)


class InvoiceDataParser:
    """Parse and validate invoice data from OCR JSON response."""
    
    def __init__(self, ocr_json: str):
        """
        Initialize parser with OCR JSON response.
        
        Args:
            ocr_json: JSON string from OCR service
        """
        self.ocr_json = ocr_json
        self.parsed_data = None
        self.errors = []
        
    def parse(self) -> Dict[str, Any]:
        """
        Parse OCR JSON and return structured data.
        
        Returns:
            dict: Parsed invoice data
            
        Raises:
            ValueError: If JSON is invalid or required fields are missing
        """
        try:
            self.parsed_data = json.loads(self.ocr_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from OCR: {str(e)}")
        
        if not isinstance(self.parsed_data, dict):
            raise ValueError("OCR response must be a JSON object")
        
        return self.parsed_data
    
    def validate_and_extract(self) -> Dict[str, Any]:
        """
        Validate and extract invoice data, handling missing fields gracefully.
        
        Returns:
            dict: Validated invoice data with defaults for missing fields
        """
        if not self.parsed_data:
            self.parse()
        
        data = {
            'invoice_number': self._get_string('invoice_number', default='UNKNOWN'),
            'date': self._get_date('date'),
            'vendor_name': self._get_string('vendor_name', default='Unknown Vendor'),
            'total_amount': self._get_decimal('total_amount', default=Decimal('0.00')),
            'state_code': self._get_string('state_code', default='').upper()[:2],
            'jurisdiction': self._get_string('jurisdiction', default=''),
            'line_items': self._get_line_items(),
        }
        
        return data
    
    def _get_string(self, key: str, default: str = '') -> str:
        """Extract string value with default."""
        value = self.parsed_data.get(key, default)
        return str(value).strip() if value else default
    
    def _get_decimal(self, key: str, default: Decimal = Decimal('0.00')) -> Decimal:
        """Extract decimal value with default."""
        value = self.parsed_data.get(key, default)
        if value is None:
            return default
        try:
            if isinstance(value, str):
                # Remove currency symbols and commas
                value = value.replace('$', '').replace(',', '').strip()
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            logger.warning(f"Invalid decimal value for {key}: {value}, using default {default}")
            return default
    
    def _get_date(self, key: str) -> Optional[datetime.date]:
        """Extract date value, trying multiple formats."""
        value = self.parsed_data.get(key)
        if not value:
            return None
        
        # Try YYYY-MM-DD format first
        if isinstance(value, str):
            try:
                return datetime.strptime(value.strip(), '%Y-%m-%d').date()
            except ValueError:
                pass
            
            # Try other common formats
            for fmt in ['%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y', '%d-%m-%Y']:
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
        
        logger.warning(f"Could not parse date: {value}")
        return None
    
    def _get_line_items(self) -> list:
        """Extract and validate line items."""
        line_items = self.parsed_data.get('line_items', [])
        if not isinstance(line_items, list):
            return []
        
        validated_items = []
        for idx, item in enumerate(line_items):
            if not isinstance(item, dict):
                logger.warning(f"Line item {idx} is not a dictionary, skipping")
                continue
            
            try:
                validated_item = {
                    'description': str(item.get('description', '')).strip() or f'Item {idx + 1}',
                    'quantity': self._get_decimal_from_dict(item, 'quantity', default=Decimal('1.00')),
                    'unit_price': self._get_decimal_from_dict(item, 'unit_price', default=Decimal('0.00')),
                    'line_total': self._get_decimal_from_dict(item, 'line_total', default=Decimal('0.00')),
                    'tax_amount': self._get_decimal_from_dict(item, 'tax_amount', default=Decimal('0.00')),
                    'tax_rate': self._get_decimal_from_dict(item, 'tax_rate', default=Decimal('0.0000')),
                    'tax_status': self._get_tax_status(item.get('tax_status', 'unknown')),
                }
                
                # Validate line_total matches quantity * unit_price if not provided
                if validated_item['line_total'] == Decimal('0.00') and validated_item['quantity'] > 0:
                    validated_item['line_total'] = validated_item['quantity'] * validated_item['unit_price']
                
                validated_items.append(validated_item)
            except Exception as e:
                logger.warning(f"Error processing line item {idx}: {str(e)}")
                continue
        
        return validated_items
    
    def _get_decimal_from_dict(self, data: dict, key: str, default: Decimal = Decimal('0.00')) -> Decimal:
        """Extract decimal from dictionary."""
        value = data.get(key, default)
        if value is None:
            return default
        try:
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default
    
    def _get_tax_status(self, status: str) -> str:
        """Validate and return tax status."""
        valid_statuses = ['taxable', 'exempt', 'unknown']
        status_lower = str(status).lower().strip()
        return status_lower if status_lower in valid_statuses else 'unknown'


def create_invoice_from_ocr(ocr_json: str, pdf_file, ocr_job=None, invoice=None) -> Invoice:
    """
    Create or update Invoice and InvoiceLineItem records from OCR JSON.
    
    Args:
        ocr_json: JSON string from OCR service
        pdf_file: Django FileField file object
        ocr_job: Optional ProcessingJob instance
        invoice: Optional existing Invoice instance to update
        
    Returns:
        Invoice: Created or updated invoice instance
        
    Raises:
        ValueError: If data is invalid
    """
    parser = InvoiceDataParser(ocr_json)
    data = parser.validate_and_extract()
    
    # Create or update invoice
    if invoice:
        invoice.invoice_number = data['invoice_number']
        invoice.date = data['date'] or timezone.now().date()
        invoice.vendor_name = data['vendor_name']
        invoice.total_amount = data['total_amount']
        invoice.state_code = data['state_code'] or 'XX'
        invoice.jurisdiction = data['jurisdiction']
        invoice.ocr_job = ocr_job
        invoice.raw_ocr_data = ocr_json
        invoice.ocr_error = ''  # Clear any previous errors
        invoice.save()
    else:
        invoice = Invoice.objects.create(
            invoice_number=data['invoice_number'],
            date=data['date'] or timezone.now().date(),
            vendor_name=data['vendor_name'],
            total_amount=data['total_amount'],
            state_code=data['state_code'] or 'XX',
            jurisdiction=data['jurisdiction'],
            pdf_file=pdf_file,
            status='processing',
            ocr_job=ocr_job,
            raw_ocr_data=ocr_json,
        )
    
    # Delete existing line items if updating
    if invoice.line_items.exists():
        invoice.line_items.all().delete()
    
    # Create line items
    for item_data in data['line_items']:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=item_data['description'],
            quantity=item_data['quantity'],
            unit_price=item_data['unit_price'],
            line_total=item_data['line_total'],
            tax_amount=item_data['tax_amount'],
            tax_rate=item_data['tax_rate'],
            tax_status=item_data['tax_status'],
        )
    
    # Update status to completed
    invoice.status = 'completed'
    invoice.processed_at = timezone.now()
    invoice.save()
    
    return invoice

