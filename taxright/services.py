"""
Service classes for processing invoice data from OCR.
"""
import json
import logging
import re
import boto3
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from django.utils import timezone
from botocore.exceptions import ClientError, BotoCoreError

from taxright.models import Invoice, InvoiceLineItem, StateKnowledgeBase, LineItemTaxVerification, TaxDetermination
from invoice_ocr.models import BedrockModelConfig

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
            'total_tax_amount': self._get_decimal('total_tax_amount', default=Decimal('0.00')),
            'invoice_discount_amount': self._get_decimal('invoice_discount_amount', default=Decimal('0.00')),
            'state_code': self._get_string('state_code', default='').upper()[:2],
            'jurisdiction': self._get_string('jurisdiction', default=''),
            'line_items': self._get_line_items(),
        }
        
        # Validate invoice totals: sum(line_totals) - invoice_discount_amount ≈ total_amount
        line_items_total = sum(item['line_total'] for item in data['line_items'])
        expected_total = line_items_total - data['invoice_discount_amount']
        tolerance = Decimal('0.01')  # Allow small rounding differences
        
        # Count how many items have line_total = 0 (might indicate OCR data quality issues)
        items_with_zero_total = sum(1 for item in data['line_items'] if item['line_total'] == Decimal('0.00'))
        total_items = len(data['line_items'])
        zero_total_ratio = items_with_zero_total / total_items if total_items > 0 else 0
        
        if abs(expected_total - data['total_amount']) > tolerance:
            # If invoice_discount_amount wasn't extracted but totals don't match, try to infer it
            # But be conservative: don't infer discount if:
            # 1. Many items have line_total = 0 (suggests OCR data quality issue, not actual discount)
            # 2. The mismatch is suspiciously large (>50% of total_amount suggests data issue)
            mismatch = line_items_total - data['total_amount']
            mismatch_ratio = mismatch / data['total_amount'] if data['total_amount'] > 0 else 0
            
            if (data['invoice_discount_amount'] == Decimal('0.00') 
                and line_items_total > data['total_amount']
                and zero_total_ratio < 0.5  # Less than 50% of items have zero line_total
                and mismatch_ratio < 0.5):  # Mismatch is less than 50% of total (reasonable discount range)
                inferred_discount = mismatch
                logger.warning(
                    f"Invoice totals don't match. Inferred invoice_discount_amount: {inferred_discount} "
                    f"(sum of line_totals: {line_items_total}, total_amount: {data['total_amount']})"
                )
                data['invoice_discount_amount'] = inferred_discount
            else:
                # Don't infer discount - likely a data quality issue
                if zero_total_ratio >= 0.5:
                    logger.warning(
                        f"Invoice totals don't match but not inferring discount: "
                        f"{items_with_zero_total}/{total_items} items have line_total=0 (likely OCR data quality issue). "
                        f"sum(line_totals)={line_items_total}, total_amount={data['total_amount']}"
                    )
                elif mismatch_ratio >= 0.5:
                    logger.warning(
                        f"Invoice totals don't match but not inferring discount: "
                        f"mismatch ({mismatch}) is {mismatch_ratio:.1%} of total_amount (too large for discount inference). "
                        f"sum(line_totals)={line_items_total}, total_amount={data['total_amount']}"
                    )
                else:
                    logger.warning(
                        f"Invoice totals don't match: sum(line_totals)={line_items_total}, "
                        f"invoice_discount_amount={data['invoice_discount_amount']}, "
                        f"expected_total={expected_total}, actual_total_amount={data['total_amount']}"
                    )
        
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
                    'discount_amount': self._get_decimal_from_dict(item, 'discount_amount', default=Decimal('0.00')),
                    'tax_amount': self._get_decimal_from_dict(item, 'tax_amount', default=Decimal('0.00')),
                    'tax_rate': self._get_decimal_from_dict(item, 'tax_rate', default=Decimal('0.0000')),
                    'tax_status': self._get_tax_status(item.get('tax_status', 'unknown')),
                }
                
                # Calculate expected line_total: (quantity * unit_price) - discount_amount
                expected_line_total = (validated_item['quantity'] * validated_item['unit_price']) - validated_item['discount_amount']
                
                # Validate line_total matches expected value
                # Only recalculate line_total if it's 0 AND we have both quantity and unit_price > 0
                # But be conservative - if OCR says line_total is 0, it might be legitimate (e.g., bundled items, OCR couldn't extract)
                if validated_item['line_total'] == Decimal('0.00') and validated_item['quantity'] > 0 and validated_item['unit_price'] > 0:
                    # Only recalculate if it seems like a calculation error (not if it's legitimately 0)
                    # We'll let the invoice-level validation decide if this creates issues
                    # For now, trust OCR's line_total = 0 unless we have strong evidence otherwise
                    # Don't auto-recalculate - this can cause false discount inference
                    pass
                else:
                    # Validate that line_total matches expected value (within tolerance for rounding)
                    tolerance = Decimal('0.01')
                    if abs(validated_item['line_total'] - expected_line_total) > tolerance:
                        logger.warning(
                            f"Line item {idx} line_total doesn't match expected value: "
                            f"line_total={validated_item['line_total']}, "
                            f"expected=(quantity * unit_price - discount)={expected_line_total}, "
                            f"quantity={validated_item['quantity']}, "
                            f"unit_price={validated_item['unit_price']}, "
                            f"discount_amount={validated_item['discount_amount']}"
                        )
                        # If discount wasn't extracted but line_total is less than quantity * unit_price, infer discount
                        pre_discount_total = validated_item['quantity'] * validated_item['unit_price']
                        if validated_item['discount_amount'] == Decimal('0.00') and validated_item['line_total'] < pre_discount_total:
                            inferred_discount = pre_discount_total - validated_item['line_total']
                            logger.info(f"Inferred discount_amount={inferred_discount} for line item {idx}")
                            validated_item['discount_amount'] = inferred_discount
                
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


def create_invoice_from_ocr(ocr_json: str, pdf_file, ocr_job=None, invoice=None, ocr_usage_info=None) -> Invoice:
    """
    Create or update Invoice and InvoiceLineItem records from OCR JSON.
    
    Args:
        ocr_json: JSON string from OCR service
        pdf_file: Django FileField file object
        ocr_job: Optional ProcessingJob instance
        invoice: Optional existing Invoice instance to update
        ocr_usage_info: Optional dict with OCR token usage and cost info (from BedrockLLMService.process_invoice)
        
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
        invoice.total_tax_amount = data['total_tax_amount']
        invoice.invoice_discount_amount = data['invoice_discount_amount']
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
            total_tax_amount=data['total_tax_amount'],
            invoice_discount_amount=data['invoice_discount_amount'],
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
            discount_amount=item_data['discount_amount'],
            tax_amount=item_data['tax_amount'],
            tax_rate=item_data['tax_rate'],
            tax_status=item_data['tax_status'],
        )
    
    # Save OCR token usage and costs if provided
    if ocr_usage_info:
        invoice.ocr_input_tokens = ocr_usage_info.get('inputTokens', 0)
        invoice.ocr_output_tokens = ocr_usage_info.get('outputTokens', 0)
        invoice.ocr_total_tokens = ocr_usage_info.get('totalTokens', 0)
        invoice.ocr_input_cost = Decimal(str(ocr_usage_info.get('inputCost', 0.0)))
        invoice.ocr_output_cost = Decimal(str(ocr_usage_info.get('outputCost', 0.0)))
        invoice.ocr_total_cost = Decimal(str(ocr_usage_info.get('totalCost', 0.0)))
    
    # Update status to completed
    invoice.status = 'completed'
    invoice.processed_at = timezone.now()
    invoice.save()
    
    # Recalculate total LLM cost (OCR cost + any existing line item KB costs)
    invoice.recalculate_total_llm_cost()
    
    # Automatically trigger tax verification if invoice has valid state code
    if invoice.state_code and invoice.state_code != 'XX' and invoice.line_items.exists():
        try:
            kb_service = BedrockKnowledgeBaseService()
            kb_service.verify_invoice_taxes(invoice)
            logger.info(f"Auto-triggered tax verification for invoice {invoice.invoice_number}")
        except Exception as e:
            # Log error but don't fail invoice creation
            logger.warning(f"Failed to auto-trigger tax verification for invoice {invoice.invoice_number}: {str(e)}")
    
    return invoice


class BedrockKnowledgeBaseService:
    """Service for querying Bedrock Knowledge Bases to verify tax correctness"""
    
    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize Bedrock Knowledge Base service.
        
        Args:
            region_name: AWS region (defaults to us-east-1)
        """
        self.region_name = region_name or 'us-east-1'
        try:
            self.client = boto3.client('bedrock-agent-runtime', region_name=self.region_name)
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {str(e)}")
            raise
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count from text length.
        Uses rough approximation: ~4 characters per token for English text.
        
        Args:
            text: Text to estimate tokens for
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Rough estimate: ~4 characters per token for English text
        return max(1, len(text) // 4)
    
    def get_knowledge_base_for_state(self, state_code: str) -> Optional[StateKnowledgeBase]:
        """
        Get the knowledge base mapping for a given state.
        
        Args:
            state_code: 2-letter US state code (e.g., 'CA', 'NY')
            
        Returns:
            StateKnowledgeBase instance or None if not found
        """
        try:
            kb = StateKnowledgeBase.objects.get(state_code=state_code.upper(), is_active=True)
            return kb
        except StateKnowledgeBase.DoesNotExist:
            logger.warning(f"No active knowledge base found for state: {state_code}")
            return None
    
    def query_knowledge_base(self, kb_id: str, query_text: str, model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0") -> Dict[str, Any]:
        """
        Query a Bedrock Knowledge Base using retrieve_and_generate API.
        
        Args:
            kb_id: Knowledge Base ID
            query_text: Query text to send to the KB
            model_id: Model ID to use for generation (default: Claude 3 Sonnet)
            
        Returns:
            Dictionary with 'answer', 'citations', and 'metadata'
            
        Raises:
            Exception: If query fails
        """
        try:
            response = self.client.retrieve_and_generate(
                input={'text': query_text},
                retrieveAndGenerateConfiguration={
                    'type': 'KNOWLEDGE_BASE',
                    'knowledgeBaseConfiguration': {
                        'knowledgeBaseId': kb_id,
                        'modelArn': f'arn:aws:bedrock:{self.region_name}::foundation-model/{model_id}'
                    }
                }
            )
            
            # Extract answer and citations
            # Handle different response structures from Bedrock
            output = response.get('output', {})
            if isinstance(output, dict):
                answer_text = output.get('text', '')
            else:
                answer_text = str(output) if output else ''
            
            # Estimate token usage
            input_tokens = self._estimate_tokens(query_text)
            output_tokens = self._estimate_tokens(answer_text)
            total_tokens = input_tokens + output_tokens
            
            result = {
                'answer': answer_text,
                'citations': response.get('citations', []),
                'metadata': {
                    'session_id': response.get('sessionId'),
                    'model_id': model_id
                },
                'token_usage': {
                    'inputTokens': input_tokens,
                    'outputTokens': output_tokens,
                    'totalTokens': total_tokens
                }
            }
            
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"AWS Bedrock KB error ({error_code}): {error_message}")
            raise Exception(f"Failed to query knowledge base: {error_message}")
        except BotoCoreError as e:
            logger.error(f"Boto3 error querying KB: {str(e)}")
            raise Exception(f"Boto3 error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error querying KB: {str(e)}")
            raise
    
    def _build_tax_verification_prompt(self, line_item: InvoiceLineItem, state_code: str, jurisdiction: str = '', invoice: Optional[Invoice] = None) -> str:
        """
        Build a structured prompt for tax verification.
        
        Args:
            line_item: InvoiceLineItem instance
            state_code: State code
            jurisdiction: Optional jurisdiction (county, city, etc.)
            invoice: Optional Invoice instance for context (total_tax_amount, etc.)
            
        Returns:
            Formatted prompt string
        """
        jurisdiction_text = f" in {jurisdiction}" if jurisdiction else ""
        
        # Format tax rate for display - tax_rate is stored as decimal (e.g., 0.0825 = 8.25%)
        applied_rate_percent = float(line_item.tax_rate) * 100
        applied_rate_decimal = float(line_item.tax_rate)
        
        # Get vendor information for context
        vendor_info = ""
        if invoice and invoice.vendor_name:
            vendor_info = f"\n- Vendor: {invoice.vendor_name} (this may help identify the type of business/service)"
        
        # Detect tax display pattern to provide context to KB
        tax_display_context = ""
        invoice_tax_info = ""
        
        if invoice:
            total_tax_amount = invoice.total_tax_amount or Decimal('0.00')
            
            # Detect tax display pattern:
            # 1. Tax shown as total: tax_amount = 0, tax_rate > 0, total_tax_amount > 0
            # 2. Tax shown per-line: tax_amount > 0
            # 3. Potentially exempt: tax_amount = 0, tax_rate = 0
            
            if line_item.tax_amount == Decimal('0.00') and line_item.tax_rate > Decimal('0.0000') and total_tax_amount > Decimal('0.00'):
                # Tax shown as total on invoice, not per-line-item
                tax_display_context = f"\nIMPORTANT TAX DISPLAY CONTEXT:\n- This invoice shows tax as a TOTAL (not per-line-item)\n- The line item has Applied Tax Amount: $0.00 because tax is calculated and shown as a single total on the invoice\n- The Applied Tax Rate ({applied_rate_percent:.4f}%) is the rate that was applied to calculate the total tax\n- The invoice has a Total Tax Amount: ${total_tax_amount:.2f} which represents the sum of all taxes\n- Please verify the APPLIED TAX RATE ({applied_rate_percent:.4f}%) is correct for this item type, not the tax amount"
                invoice_tax_info = f"\n- Invoice Total Tax Amount: ${total_tax_amount:.2f} (tax shown as total, not per-line-item)"
            elif line_item.tax_amount > Decimal('0.00'):
                # Tax shown per-line-item
                tax_display_context = f"\nIMPORTANT TAX DISPLAY CONTEXT:\n- This invoice shows tax per-line-item\n- The Applied Tax Amount (${line_item.tax_amount:.2f}) is the tax calculated for this specific line item"
            elif line_item.tax_amount == Decimal('0.00') and line_item.tax_rate == Decimal('0.0000'):
                # Potentially exempt
                tax_display_context = f"\nIMPORTANT TAX DISPLAY CONTEXT:\n- This line item shows no tax (tax_amount = $0.00, tax_rate = 0.0000)\n- This may indicate the item is tax-exempt or not subject to tax\n- Please verify if this item type should be exempt from tax in {state_code}{jurisdiction_text}"
        
        prompt = f"""You are a tax law expert for {state_code}{jurisdiction_text}. 

Analyze the following invoice line item and determine if the tax that was applied is correct according to state tax law.

Invoice Context:{vendor_info}

Line Item Details:
- Description: {line_item.description}
- Quantity: {line_item.quantity}
- Unit Price: ${line_item.unit_price}
- Line Total: ${line_item.line_total}
- Tax Status: {line_item.get_tax_status_display()}
- Applied Tax Rate: {applied_rate_percent:.4f}% (as decimal: {applied_rate_decimal})
- Applied Tax Amount: ${line_item.tax_amount}{invoice_tax_info}{tax_display_context}

Please determine:
1. Is the tax rate applied to this item correct according to {state_code} state tax law?
2. What is the expected tax rate for this type of item in {state_code}{jurisdiction_text}? (Provide as a decimal, e.g., 0.0825 for 8.25%)
3. Provide your confidence level (0.0 to 1.0) in your determination
4. Explain your reasoning based on the relevant tax laws

IMPORTANT VERIFICATION GUIDELINES: 
- Focus on verifying the APPLIED TAX RATE ({applied_rate_percent:.4f}%), not the tax amount
- The applied tax rate shown above is {applied_rate_percent:.4f}% (NOT 0% - please use the exact value shown)
- Compare the applied rate ({applied_rate_percent:.4f}%) to the expected rate for this item type
- CRITICAL CONSISTENCY RULE: If expected_tax_rate ≠ applied_tax_rate (beyond 0.0001 tolerance), then is_correct MUST be false
- Set is_correct to true ONLY if the applied rate matches the expected rate (within 0.0001 tolerance)
- Your reasoning must be consistent with your is_correct determination - if you state the expected rate differs from the applied rate, is_correct must be false
- If the Applied Tax Amount is $0.00 but the Applied Tax Rate is > 0%, this means tax is shown as a total on the invoice (not per-line-item) - still verify the rate is correct
- The tax amount ($0.00 or otherwise) is for reference only - your verification should be based on whether the TAX RATE is correct for this item type

CRITICAL RATE MATCHING GUIDELINES:
- If the invoice shows tax_rate = {applied_rate_percent:.4f}% and tax_status = 'taxable', the expected_tax_rate should typically be {applied_rate_decimal} (matching the applied rate) unless this specific item type is explicitly exempt from tax
- Example: If invoice shows tax_rate = 0.0675 (6.75%) and tax_status = 'taxable', the expected_tax_rate should typically be 0.0675 unless this item type is exempt
- Only set expected_tax_rate = 0.0000 if the item type is explicitly exempt from tax according to state law
- Precision differences (e.g., 6.75% vs 6.7500%) are NOT actual differences - these represent the same rate with different decimal precision
- Do NOT mark items as incorrect due to precision-only differences in rate formatting

Respond in JSON format with the following structure:
{{
    "is_correct": true/false,
    "expected_tax_rate": 0.0825,
    "confidence_score": 0.95,
    "reasoning": "Detailed explanation based on state tax law..."
}}

IMPORTANT:
- Return ONLY valid JSON, no additional text or markdown formatting
- Keep the reasoning field concise (under 500 characters)
- Do not include URLs or external links in the reasoning field
- Ensure all quotes in the reasoning field are properly escaped
- The JSON must be complete and valid
- expected_tax_rate should be a decimal (e.g., 0.0825 for 8.25%, not 8.25)"""
        
        return prompt
    
    def _parse_verification_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse the JSON response from KB query.
        
        Args:
            response_text: Raw response text from KB
            
        Returns:
            Parsed dictionary with verification results
        """
        # Try to extract JSON from response (might be wrapped in markdown)
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            # Try to find JSON object directly - look for opening brace
            json_pattern = r'(\{.*)'
            match = re.search(json_pattern, response_text, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
            else:
                json_str = response_text.strip()
        
        # Try to fix incomplete JSON by finding the last complete field
        # If JSON is truncated, try to extract what we can
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            # Try to fix common issues:
            # 1. Truncated reasoning field - try to extract up to the error position
            # 2. Unescaped quotes in reasoning
            logger.warning(f"Initial JSON parse failed: {str(e)}. Attempting to fix...")
            
            # Try to extract fields manually using regex as fallback
            is_correct_match = re.search(r'"is_correct"\s*:\s*(true|false)', json_str, re.IGNORECASE)
            expected_rate_match = re.search(r'"expected_tax_rate"\s*:\s*([0-9.]+)', json_str)
            confidence_match = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', json_str)
            reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', json_str, re.DOTALL)
            
            # If reasoning match failed, try to get everything after "reasoning": "
            if not reasoning_match:
                reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)(?:"\s*[,}])', json_str, re.DOTALL)
            
            # If still no match, try to get everything after reasoning up to end or next field
            if not reasoning_match:
                reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)(?=\s*"|$)', json_str, re.DOTALL)
            
            try:
                parsed = {
                    'is_correct': is_correct_match.group(1).lower() == 'true' if is_correct_match else False,
                    'expected_tax_rate': float(expected_rate_match.group(1)) if expected_rate_match else 0.0,
                    'confidence_score': float(confidence_match.group(1)) if confidence_match else 0.5,
                    'reasoning': reasoning_match.group(1) if reasoning_match else 'Reasoning field could not be extracted from response'
                }
                logger.info("Successfully extracted fields using regex fallback")
            except Exception as fallback_error:
                logger.error(f"Fallback parsing also failed: {str(fallback_error)}")
                # Last resort: try to parse what we can and use defaults
                parsed = {
                    'is_correct': False,
                    'expected_tax_rate': 0.0,
                    'confidence_score': 0.0,
                    'reasoning': f"Failed to parse JSON response. Error: {str(e)}. Response preview: {response_text[:300]}"
                }
        
        # Validate and normalize response
        try:
            result = {
                'is_correct': bool(parsed.get('is_correct', False)),
                'expected_tax_rate': Decimal(str(parsed.get('expected_tax_rate', 0))),
                'confidence_score': Decimal(str(parsed.get('confidence_score', 0.5))),
                'reasoning': str(parsed.get('reasoning', 'No reasoning provided')).strip()
            }
            
            # Clamp confidence score to 0-1
            if result['confidence_score'] < 0:
                result['confidence_score'] = Decimal('0.00')
            elif result['confidence_score'] > 1:
                result['confidence_score'] = Decimal('1.00')
            
            return result
            
        except Exception as e:
            logger.error(f"Error normalizing parsed response: {str(e)}")
            # Return default values if normalization fails
            return {
                'is_correct': False,
                'expected_tax_rate': Decimal('0.0000'),
                'confidence_score': Decimal('0.00'),
                'reasoning': f"Error processing response: {str(e)}. Response preview: {response_text[:300]}"
            }
    
    def _normalize_rate_mentions(self, text: str) -> str:
        """
        Normalize rate mentions in text to remove precision-only differences.
        
        This helps detect when reasoning mentions the same rate with different
        decimal precision (e.g., "6.75%" vs "6.7500%") as if they're different.
        
        Args:
            text: Text that may contain rate mentions
            
        Returns:
            Normalized text with rates rounded to 4 decimal places
        """
        import re
        
        # Pattern to match percentage rates: digits, optional decimal, digits, %
        rate_pattern = r'(\d+\.?\d*)\s*%'
        
        def normalize_rate(match):
            rate_str = match.group(1)
            try:
                # Convert to decimal, round to 4 decimal places, convert back
                rate_decimal = Decimal(rate_str)
                normalized = rate_decimal.quantize(Decimal('0.0001'))
                return f"{normalized}%"
            except (InvalidOperation, ValueError):
                # If conversion fails, return original
                return match.group(0)
        
        # Replace all rate mentions with normalized versions
        normalized_text = re.sub(rate_pattern, normalize_rate, text)
        return normalized_text
    
    def _extract_rates_from_reasoning(self, reasoning: str) -> list:
        """
        Extract all rate mentions from reasoning text as Decimal values.
        
        Args:
            reasoning: Reasoning text that may contain rate mentions
            
        Returns:
            List of Decimal rate values (as decimals, not percentages)
        """
        import re
        rates = []
        rate_pattern = r'(\d+\.?\d*)\s*%'
        matches = re.findall(rate_pattern, reasoning)
        for rate_str in matches:
            try:
                rate_decimal = Decimal(rate_str) / 100  # Convert percentage to decimal
                rates.append(rate_decimal)
            except (InvalidOperation, ValueError):
                continue
        return rates
    
    def _validate_tax_rate(self, rate: Any, line_item_id: Optional[int] = None) -> Decimal:
        """
        Validate and clamp tax rate to reasonable bounds (0.0 to 1.0).
        
        Args:
            rate: Tax rate value (can be Decimal, float, int, str, or None)
            line_item_id: Optional line item ID for logging context
            
        Returns:
            Validated Decimal tax rate clamped to [0.0, 1.0]
        """
        try:
            if rate is None:
                logger.warning(f"Tax rate is None for line_item_id={line_item_id}, using 0.0")
                return Decimal('0.0000')
            
            # Convert to Decimal
            rate_decimal = Decimal(str(rate))
            
            # Clamp to reasonable bounds (0.0 to 1.0 for 0% to 100%)
            if rate_decimal < Decimal('0.0'):
                logger.warning(f"Tax rate {rate_decimal} is negative for line_item_id={line_item_id}, clamping to 0.0")
                return Decimal('0.0000')
            elif rate_decimal > Decimal('1.0'):
                logger.warning(f"Tax rate {rate_decimal} exceeds 1.0 (100%) for line_item_id={line_item_id}, clamping to 1.0")
                return Decimal('1.0000')
            
            return rate_decimal.quantize(Decimal('0.0001'))  # 4 decimal places for rates
            
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Invalid tax rate value '{rate}' for line_item_id={line_item_id}: {str(e)}, using 0.0")
            return Decimal('0.0000')
    
    def verify_line_item_tax(self, line_item: InvoiceLineItem, state_code: str, jurisdiction: str = '', invoice: Optional[Invoice] = None) -> Dict[str, Any]:
        """
        Verify if tax applied to a line item is correct using Bedrock KB.
        
        Args:
            line_item: InvoiceLineItem instance
            state_code: State code
            jurisdiction: Optional jurisdiction
            invoice: Optional Invoice instance for context (total_tax_amount, etc.)
            
        Returns:
            Dictionary with verification results including:
            - is_correct: bool
            - expected_tax_rate: Decimal
            - confidence_score: Decimal
            - reasoning: str
            - kb_response: dict (full KB response)
        """
        # Get invoice if not provided (line_item has invoice FK)
        if invoice is None:
            invoice = line_item.invoice
        
        # Get KB for state
        kb = self.get_knowledge_base_for_state(state_code)
        if not kb:
            logger.warning(f"No KB mapping found for state {state_code}")
            return {
                'is_correct': False,
                'expected_tax_rate': Decimal('0.0000'),
                'confidence_score': Decimal('0.00'),
                'reasoning': f"No knowledge base configured for state {state_code}. Please configure a knowledge base mapping in the admin.",
                'kb_response': None,
                'error': 'NO_KB_MAPPING'
            }
        
        # Build prompt with invoice context
        prompt = self._build_tax_verification_prompt(line_item, state_code, jurisdiction, invoice=invoice)
        
        try:
            # Query KB
            kb_response = self.query_knowledge_base(kb.knowledge_base_id, prompt)
            
            if not kb_response:
                raise Exception("Empty response from knowledge base")
            
            # Parse response
            answer = kb_response.get('answer', '')
            if not answer:
                raise Exception("No answer in KB response")
            
            verification = self._parse_verification_response(answer)
            
            # Validate consistency between expected/applied rates and is_correct
            applied_rate = Decimal(str(line_item.tax_rate))
            expected_rate = verification['expected_tax_rate']
            tolerance = Decimal('0.0001')  # Allow small floating point differences
            
            # Handle case where KB returns 0.0000 expected rate for taxable items
            # Check if reasoning contradicts the zero rate
            if expected_rate == Decimal('0.0000') and applied_rate > Decimal('0.0000'):
                # KB returned zero expected rate but item has applied tax
                # Check reasoning to see if it actually suggests the item should be taxable
                reasoning_lower = verification['reasoning'].lower()
                rates_in_reasoning = self._extract_rates_from_reasoning(verification['reasoning'])
                
                # Check if reasoning mentions a non-zero tax rate
                reasoning_suggests_taxable = False
                for mentioned_rate in rates_in_reasoning:
                    if mentioned_rate > tolerance:
                        # Reasoning mentions a non-zero rate
                        if abs(mentioned_rate - applied_rate) <= tolerance:
                            # The mentioned rate matches the applied rate
                            reasoning_suggests_taxable = True
                            logger.info(
                                f"KB returned expected_rate=0.0000 but reasoning mentions rate {mentioned_rate} "
                                f"that matches applied_rate={applied_rate}. Using applied_rate as expected_rate."
                            )
                            expected_rate = applied_rate
                            verification['expected_tax_rate'] = expected_rate
                            break
                        elif mentioned_rate > tolerance:
                            # Reasoning mentions a different non-zero rate
                            reasoning_suggests_taxable = True
                            logger.info(
                                f"KB returned expected_rate=0.0000 but reasoning mentions rate {mentioned_rate}. "
                                f"Using mentioned rate as expected_rate."
                            )
                            expected_rate = mentioned_rate
                            verification['expected_tax_rate'] = expected_rate
                            break
                
                # If item is marked as taxable in OCR and reasoning doesn't explicitly say it's exempt,
                # treat the zero expected rate as likely incorrect
                if not reasoning_suggests_taxable and line_item.tax_status == 'taxable':
                    exempt_keywords = ['exempt', 'not subject to tax', 'no tax', 'tax-free', 'non-taxable']
                    reasoning_explicitly_exempt = any(keyword in reasoning_lower for keyword in exempt_keywords)
                    
                    if not reasoning_explicitly_exempt:
                        # Item is taxable but KB returned 0.0000 without clear exemption reasoning
                        # Use applied rate as expected rate (likely KB error)
                        logger.warning(
                            f"KB returned expected_rate=0.0000 for taxable item (tax_status='taxable', "
                            f"applied_rate={applied_rate}) without explicit exemption reasoning. "
                            f"Using applied_rate as expected_rate."
                        )
                        expected_rate = applied_rate
                        verification['expected_tax_rate'] = expected_rate
            
            rates_match = abs(applied_rate - expected_rate) <= tolerance
            
            # CRITICAL: Enforce consistency - if rates don't match, is_correct MUST be false
            if not rates_match:
                if verification['is_correct']:
                    logger.warning(
                        f"Auto-correcting is_correct: rates don't match but KB said correct. "
                        f"Applied={applied_rate}, Expected={expected_rate}, "
                        f"Difference={abs(applied_rate - expected_rate)}"
                    )
                    verification['is_correct'] = False
                    # Update reasoning to note the correction
                    verification['reasoning'] = (
                        f"[Auto-corrected] The applied tax rate ({applied_rate * 100:.4f}%) does not match "
                        f"the expected rate ({expected_rate * 100:.4f}%), so is_correct has been set to false. "
                        f"Original reasoning: {verification['reasoning']}"
                    )
            else:
                # Rates match - override KB's is_correct if it's wrong
                if not verification['is_correct']:
                    logger.info(f"Auto-correcting is_correct: rates match (applied={applied_rate}, expected={expected_rate})")
                    verification['is_correct'] = True
                    # Update reasoning to note the correction
                    if "applied tax rate of 0%" in verification['reasoning'].lower():
                        verification['reasoning'] = f"[Auto-corrected] The applied tax rate ({applied_rate * 100:.4f}%) matches the expected rate ({expected_rate * 100:.4f}%). " + verification['reasoning']
            
            # Additional validation: Check for contradictory reasoning text
            # If reasoning mentions expected rate differs from applied rate but is_correct is true, correct it
            # Also detect precision-only differences (e.g., "6.75%" vs "6.7500%")
            reasoning_lower = verification['reasoning'].lower()
            normalized_reasoning = self._normalize_rate_mentions(verification['reasoning'])
            
            if verification['is_correct']:
                # Check for phrases that suggest rates don't match
                contradiction_phrases = [
                    'expected rate differs',
                    'expected rate is different',
                    'expected rate does not match',
                    'applied rate does not match',
                    'applied rate differs',
                    'applied rate is different',
                    'should be',
                    'should have been',
                    'technically incorrect',
                ]
                
                # Extract all rate mentions from reasoning
                rates_in_reasoning = self._extract_rates_from_reasoning(verification['reasoning'])
                
                # Check for actual contradictions (rates that differ beyond tolerance)
                found_contradiction = False
                for mentioned_rate in rates_in_reasoning:
                    # Check if mentioned rate differs from applied rate (beyond tolerance)
                    if abs(mentioned_rate - applied_rate) > tolerance:
                        # Check if mentioned rate matches expected rate (within tolerance)
                        if abs(mentioned_rate - expected_rate) <= tolerance:
                            # Reasoning mentions expected rate that differs from applied
                            # This is a real contradiction
                            logger.warning(
                                f"Detected contradictory reasoning: reasoning mentions rate {mentioned_rate} "
                                f"but is_correct is true with applied_rate={applied_rate}, expected_rate={expected_rate}"
                            )
                            verification['is_correct'] = False
                            verification['reasoning'] = (
                                f"[Auto-corrected] Contradictory reasoning detected. "
                                f"The reasoning suggests the expected rate ({mentioned_rate * 100:.4f}%) differs from the applied rate ({applied_rate * 100:.4f}%), "
                                f"so is_correct has been set to false. Original reasoning: {verification['reasoning']}"
                            )
                            found_contradiction = True
                            break
                
                # Check for precision-only differences (false positives)
                # If reasoning mentions rates that are the same when normalized, but uses phrases suggesting they differ
                if not found_contradiction:
                    for phrase in contradiction_phrases:
                        if phrase in reasoning_lower:
                            # Check if all mentioned rates, when normalized, match applied/expected rates
                            all_rates_match = True
                            for mentioned_rate in rates_in_reasoning:
                                # Check if mentioned rate matches applied or expected (within tolerance)
                                matches_applied = abs(mentioned_rate - applied_rate) <= tolerance
                                matches_expected = abs(mentioned_rate - expected_rate) <= tolerance
                                if not (matches_applied or matches_expected):
                                    all_rates_match = False
                                    break
                            
                            # If all rates match but reasoning suggests they don't, it's a precision-only difference
                            if all_rates_match and rates_in_reasoning:
                                logger.info(
                                    f"Detected precision-only difference in reasoning: rates match but reasoning suggests they don't. "
                                    f"Applied={applied_rate}, Expected={expected_rate}, Mentioned rates={rates_in_reasoning}"
                                )
                                # Don't change is_correct since rates actually match
                                # But update reasoning to clarify
                                if "technically incorrect" in reasoning_lower or "does not match" in reasoning_lower:
                                    verification['reasoning'] = (
                                        f"[Clarified] The applied tax rate ({applied_rate * 100:.4f}%) matches the expected rate ({expected_rate * 100:.4f}%). "
                                        f"Any mention of rate differences in the original reasoning referred to decimal precision formatting, not actual rate differences. "
                                        f"Original reasoning: {verification['reasoning']}"
                                    )
                                break
            
            # Add KB metadata
            verification['kb_response'] = kb_response
            verification['kb_id'] = kb.knowledge_base_id
            verification['kb_name'] = kb.knowledge_base_name
            
            # Calculate and save token costs to line item
            token_usage = kb_response.get('token_usage', {})
            input_tokens = token_usage.get('inputTokens', 0)
            output_tokens = token_usage.get('outputTokens', 0)
            total_tokens = token_usage.get('totalTokens', 0)
            
            # Get model pricing (default to Claude 3 Sonnet pricing)
            model_id = kb_response.get('metadata', {}).get('model_id', 'anthropic.claude-3-sonnet-20240229-v1:0')
            try:
                model_config = BedrockModelConfig.objects.get(model_id=model_id, is_active=True)
                input_cost_per_1k = float(model_config.input_token_cost)
                output_cost_per_1k = float(model_config.output_token_cost)
            except BedrockModelConfig.DoesNotExist:
                # Default Claude 3 Sonnet pricing if model not found
                logger.warning(f"Model config not found for {model_id}, using default pricing")
                input_cost_per_1k = 0.003  # $0.003 per 1K input tokens
                output_cost_per_1k = 0.015  # $0.015 per 1K output tokens
            
            # Calculate costs
            input_cost = (input_tokens / 1000.0) * input_cost_per_1k
            output_cost = (output_tokens / 1000.0) * output_cost_per_1k
            total_cost = input_cost + output_cost
            
            # Save to line item
            line_item.kb_input_tokens = input_tokens
            line_item.kb_output_tokens = output_tokens
            line_item.kb_total_tokens = total_tokens
            line_item.kb_input_cost = Decimal(str(round(input_cost, 8)))
            line_item.kb_output_cost = Decimal(str(round(output_cost, 8)))
            line_item.kb_total_cost = Decimal(str(round(total_cost, 8)))
            line_item.save(update_fields=[
                'kb_input_tokens', 'kb_output_tokens', 'kb_total_tokens',
                'kb_input_cost', 'kb_output_cost', 'kb_total_cost', 'updated_at'
            ])
            
            return verification
            
        except Exception as e:
            logger.error(f"Error verifying line item tax (line_item_id={line_item.id}, state={state_code}): {str(e)}", exc_info=True)
            return {
                'is_correct': False,
                'expected_tax_rate': Decimal('0.0000'),
                'confidence_score': Decimal('0.00'),
                'reasoning': f"Error during verification: {str(e)}",
                'kb_response': None,
                'error': str(e)
            }
    
    def verify_invoice_taxes(self, invoice: Invoice) -> Dict[str, Any]:
        """
        Verify taxes for all line items in an invoice.
        
        Args:
            invoice: Invoice instance
            
        Returns:
            Dictionary with:
            - line_item_verifications: list of verification results
            - summary: aggregated summary
        """
        if not invoice.state_code or invoice.state_code == 'XX':
            return {
                'line_item_verifications': [],
                'summary': {
                    'error': 'No valid state code for invoice'
                }
            }
        
        verifications = []
        for line_item in invoice.line_items.all():
            verification_result = self.verify_line_item_tax(
                line_item,
                invoice.state_code,
                invoice.jurisdiction,
                invoice=invoice
            )
            
            # Create or update LineItemTaxVerification record
            verification_obj, created = LineItemTaxVerification.objects.update_or_create(
                line_item=line_item,
                defaults={
                    'is_correct': verification_result['is_correct'],
                    'confidence_score': verification_result['confidence_score'],
                    'reasoning': verification_result['reasoning'],
                    'expected_tax_rate': verification_result['expected_tax_rate'],
                    'applied_tax_rate': line_item.tax_rate,
                    'verification_details': {
                        'kb_id': verification_result.get('kb_id'),
                        'kb_name': verification_result.get('kb_name'),
                        'citations': (verification_result.get('kb_response') or {}).get('citations', []),
                        'error': verification_result.get('error')
                    }
                }
            )
            
            verifications.append({
                'line_item_id': line_item.id,
                'verification_id': verification_obj.id,
                'is_correct': verification_result['is_correct'],
                'confidence_score': float(verification_result['confidence_score']),
                'reasoning': verification_result['reasoning'],
                'expected_tax_rate': float(verification_result['expected_tax_rate']),
                'applied_tax_rate': float(line_item.tax_rate),
                'kb_id': verification_result.get('kb_id'),
                'kb_name': verification_result.get('kb_name')
            })
        
        # Calculate summary
        total_items = len(verifications)
        correct_items = sum(1 for v in verifications if v['is_correct'])
        avg_confidence = sum(v['confidence_score'] for v in verifications) / total_items if total_items > 0 else 0
        
        summary = {
            'total_line_items': total_items,
            'correct_tax_applications': correct_items,
            'incorrect_tax_applications': total_items - correct_items,
            'average_confidence': avg_confidence,
            'all_correct': correct_items == total_items
        }
        
        # Update or create TaxDetermination
        # Calculate expected tax and actual tax with proper validation and rounding
        
        # Handle edge case: empty verifications list
        if not verifications:
            logger.warning(f"No verifications available for invoice {invoice.invoice_number}, will use applied tax rates for expected tax calculation")
        
        try:
            # Calculate expected tax only for taxable items
            # Use expected_tax_rate from KB response (not applied rate from invoice)
            # Create a mapping of line_item_id to validated expected_tax_rate from verifications
            expected_rate_map = {}
            for v in verifications:
                line_item_id = v['line_item_id']
                raw_rate = v.get('expected_tax_rate', 0.0)
                # Validate and clamp the expected tax rate
                validated_rate = self._validate_tax_rate(raw_rate, line_item_id=line_item_id)
                expected_rate_map[line_item_id] = validated_rate
            
            # Calculate expected tax for each taxable line item
            # Handle edge cases: failed verifications, zero line totals, missing verifications
            total_expected_tax = Decimal('0.00')
            zero_rate_fallback_count = 0
            fallback_rate_updates = {}  # Track which verifications need to be updated with fallback rates
            
            # First pass: identify which items will be included in tax calculation and calculate taxable subtotal
            # This is needed to properly allocate invoice-level discounts only to taxable items
            taxable_items = []
            taxable_subtotal = Decimal('0.00')
            for line_item in invoice.line_items.all():
                expected_rate = expected_rate_map.get(line_item.id)
                # Determine if item should be included in expected tax calculation
                if line_item.tax_status != 'taxable':
                    if expected_rate is None or expected_rate == Decimal('0.0000'):
                        continue  # Skip exempt items
                # Item will be included - add to taxable subtotal
                taxable_items.append((line_item, expected_rate))
                taxable_subtotal += line_item.line_total
            
            # Calculate subtotal of all line items for validation/warning purposes
            subtotal = sum(line_item.line_total for line_item in invoice.line_items.all())
            
            # Determine if line_totals already include invoice-level discount
            # If subtotal ≈ total_amount (within tolerance), line_totals are post-discount
            # If subtotal ≈ total_amount + invoice_discount_amount, line_totals are pre-discount
            tolerance = Decimal('0.01')
            line_totals_include_discount = False
            if invoice.invoice_discount_amount and invoice.invoice_discount_amount > Decimal('0.00'):
                # Check if line_totals are already post-discount
                if abs(subtotal - invoice.total_amount) <= tolerance:
                    line_totals_include_discount = True
                    logger.info(
                        f"Invoice {invoice.invoice_number}: line_totals appear to already include invoice-level discount "
                        f"(subtotal={subtotal}, total_amount={invoice.total_amount})"
                    )
                elif abs(subtotal - (invoice.total_amount + invoice.invoice_discount_amount)) <= tolerance:
                    line_totals_include_discount = False
                    logger.info(
                        f"Invoice {invoice.invoice_number}: line_totals are pre-discount "
                        f"(subtotal={subtotal}, total_amount={invoice.total_amount}, invoice_discount_amount={invoice.invoice_discount_amount})"
                    )
            
            # Second pass: calculate expected tax for taxable items
            for line_item, expected_rate in taxable_items:
                # Item is already confirmed to be taxable - proceed with tax calculation
                # Use expected rate from verification, or fallback to applied rate
                
                # If verification failed (expected_rate is 0.0000) but line item has applied tax_rate,
                # use applied rate as fallback with a warning
                if expected_rate is None:
                    # No verification found - use applied rate as fallback
                    expected_rate = self._validate_tax_rate(line_item.tax_rate, line_item_id=line_item.id)
                    logger.warning(f"No verification found for line_item_id={line_item.id}, using applied tax_rate={expected_rate}")
                    # Track that we're using fallback - will update verification later
                    fallback_rate_updates[line_item.id] = expected_rate
                elif expected_rate == Decimal('0.0000') and line_item.tax_rate > Decimal('0.0000'):
                    # Verification returned 0.0000 but item has applied tax - use applied rate as fallback
                    expected_rate = self._validate_tax_rate(line_item.tax_rate, line_item_id=line_item.id)
                    zero_rate_fallback_count += 1
                    logger.warning(
                        f"Verification returned 0.0000 for taxable line_item_id={line_item.id} "
                        f"with applied_rate={line_item.tax_rate}, using applied rate as fallback for expected tax calculation"
                    )
                    # Track that we're using fallback - will update verification later
                    fallback_rate_updates[line_item.id] = expected_rate
                
                # Calculate expected tax for this line item
                # line_total is validated to be >= 0 by model, but handle edge case defensively
                if line_item.line_total < Decimal('0.00'):
                    logger.warning(f"Negative line_total {line_item.line_total} for line_item_id={line_item.id}, treating as 0.00")
                    base_line_total = Decimal('0.00')
                else:
                    base_line_total = line_item.line_total
                
                # Apply invoice-level discount proportionally if present
                # For line-item discounts, line_total should already reflect the discount
                # IMPORTANT: Allocate discount only to taxable items (use taxable_subtotal, not total subtotal)
                # Only apply invoice-level discount if line_totals are pre-discount
                if (invoice.invoice_discount_amount and invoice.invoice_discount_amount > Decimal('0.00') 
                    and taxable_subtotal > Decimal('0.00') and not line_totals_include_discount):
                    # Calculate proportional discount for this line item based on taxable subtotal
                    proportional_discount = invoice.invoice_discount_amount * (base_line_total / taxable_subtotal)
                    discounted_amount = base_line_total - proportional_discount
                    # Ensure discounted amount is non-negative
                    if discounted_amount < Decimal('0.00'):
                        logger.warning(
                            f"Proportional discount {proportional_discount} exceeds line_total {base_line_total} "
                            f"for line_item_id={line_item.id}, using 0.00"
                        )
                        discounted_amount = Decimal('0.00')
                else:
                    # No invoice-level discount to apply (either none exists, or line_totals already include it)
                    # Use line_total directly (which should already reflect line-item discounts and possibly invoice-level discount)
                    discounted_amount = base_line_total
                
                # Calculate tax on the discounted amount
                line_expected_tax = expected_rate * discounted_amount
                total_expected_tax += line_expected_tax
                
                # Warn if line_total appears to be pre-discount (sum of line_totals > total_amount + invoice_discount_amount)
                if subtotal > invoice.total_amount + invoice.invoice_discount_amount + Decimal('0.01'):
                    logger.warning(
                        f"Line item {line_item.id} line_total may be pre-discount: "
                        f"line_total={base_line_total}, unit_price={line_item.unit_price}, "
                        f"quantity={line_item.quantity}, discount_amount={line_item.discount_amount}"
                    )
            
            # Log summary of fallback usage
            if zero_rate_fallback_count > 0:
                logger.info(f"Used applied tax_rate as fallback for {zero_rate_fallback_count} line items with zero expected_tax_rate")
            
            # Update verification records to reflect fallback rates used in expected tax calculation
            # This ensures verification status is consistent with expected tax calculation
            for line_item_id, fallback_rate in fallback_rate_updates.items():
                try:
                    line_item = InvoiceLineItem.objects.get(id=line_item_id)
                    # Update the most recent verification for this line item
                    verification = line_item.tax_verifications.order_by('-verified_at').first()
                    if verification:
                        # Only update if the expected_rate was 0.0000 (not if it was None)
                        if verification.expected_tax_rate == Decimal('0.0000'):
                            verification.expected_tax_rate = fallback_rate
                            # Recalculate is_correct based on updated expected rate
                            applied_rate = Decimal(str(line_item.tax_rate))
                            tolerance = Decimal('0.0001')
                            rates_match = abs(applied_rate - fallback_rate) <= tolerance
                            if rates_match:
                                verification.is_correct = True
                                verification.reasoning = (
                                    f"[Updated] Expected tax rate updated from 0.0000 to {fallback_rate * 100:.4f}% "
                                    f"(using applied rate as fallback). Rates match, so is_correct set to true. "
                                    f"Original reasoning: {verification.reasoning}"
                                )
                            else:
                                verification.is_correct = False
                                verification.reasoning = (
                                    f"[Updated] Expected tax rate updated from 0.0000 to {fallback_rate * 100:.4f}% "
                                    f"(using applied rate as fallback). Rates don't match. "
                                    f"Original reasoning: {verification.reasoning}"
                                )
                            verification.save(update_fields=['expected_tax_rate', 'is_correct', 'reasoning', 'updated_at'])
                            logger.info(
                                f"Updated verification for line_item_id={line_item_id}: "
                                f"expected_tax_rate={fallback_rate}, is_correct={verification.is_correct}"
                            )
                except InvoiceLineItem.DoesNotExist:
                    logger.warning(f"Line item {line_item_id} not found when updating verification with fallback rate")
                except Exception as e:
                    logger.error(f"Error updating verification for line_item_id={line_item_id} with fallback rate: {str(e)}")
            
            # Round expected tax to 2 decimal places (currency precision)
            total_expected_tax = total_expected_tax.quantize(Decimal('0.01'))
            
            # Calculate actual tax
            # Strategy: Use invoice.total_tax_amount if available and > 0 (when tax is shown as total, not per-line-item),
            # otherwise sum line item tax amounts
            # This handles cases where invoices show tax as a single total rather than per-line-item
            if invoice.total_tax_amount and invoice.total_tax_amount > Decimal('0.00'):
                # Invoice has a total tax amount - use it
                total_actual_tax = invoice.total_tax_amount
            else:
                # Sum individual line item tax amounts
                total_actual_tax = sum(
                    max(Decimal('0.00'), line_item.tax_amount)  # Ensure non-negative
                    for line_item in invoice.line_items.all()
                )
            
            # Validate actual tax is non-negative
            if total_actual_tax < Decimal('0.00'):
                logger.warning(f"Negative total_actual_tax {total_actual_tax} for invoice {invoice.invoice_number}, clamping to 0.00")
                total_actual_tax = Decimal('0.00')
            
            # Round actual tax to 2 decimal places (currency precision)
            total_actual_tax = total_actual_tax.quantize(Decimal('0.01'))
            
        except Exception as e:
            logger.error(f"Error calculating tax amounts for invoice {invoice.invoice_number}: {str(e)}", exc_info=True)
            # Fallback to safe defaults on error
            total_expected_tax = Decimal('0.00')
            total_actual_tax = invoice.total_tax_amount if invoice.total_tax_amount and invoice.total_tax_amount > Decimal('0.00') else Decimal('0.00')
        
        # Get KB info from first verification that has it
        kb_id = None
        kb_name = None
        for v in verifications:
            if v.get('kb_id'):
                kb_id = v.get('kb_id')
                kb_name = v.get('kb_name')
                break
        
        determination, _ = TaxDetermination.objects.update_or_create(
            invoice=invoice,
            defaults={
                'determination_status': 'verified' if summary['all_correct'] else 'discrepancy',
                'expected_tax': total_expected_tax,
                'actual_tax': total_actual_tax,
                'discrepancy_amount': total_actual_tax - total_expected_tax,
                'verified_at': timezone.now(),
                'kb_verification_metadata': {
                    'kb_id': kb_id,
                    'kb_name': kb_name,
                    'summary': summary,
                    'verification_count': total_items
                }
            }
        )
        
        # Recalculate total LLM cost
        invoice.recalculate_total_llm_cost()
        
        return {
            'line_item_verifications': verifications,
            'summary': summary,
            'tax_determination_id': determination.id
        }

