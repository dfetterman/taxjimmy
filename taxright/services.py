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
    
    def _build_tax_verification_prompt(self, line_item: InvoiceLineItem, state_code: str, jurisdiction: str = '') -> str:
        """
        Build a structured prompt for tax verification.
        
        Args:
            line_item: InvoiceLineItem instance
            state_code: State code
            jurisdiction: Optional jurisdiction (county, city, etc.)
            
        Returns:
            Formatted prompt string
        """
        jurisdiction_text = f" in {jurisdiction}" if jurisdiction else ""
        
        # Format tax rate for display - tax_rate is stored as decimal (e.g., 0.0825 = 8.25%)
        applied_rate_percent = float(line_item.tax_rate) * 100
        applied_rate_decimal = float(line_item.tax_rate)
        
        prompt = f"""You are a tax law expert for {state_code}{jurisdiction_text}. 

Analyze the following invoice line item and determine if the tax that was applied is correct according to state tax law.

Line Item Details:
- Description: {line_item.description}
- Quantity: {line_item.quantity}
- Unit Price: ${line_item.unit_price}
- Line Total: ${line_item.line_total}
- Tax Status: {line_item.get_tax_status_display()}
- Applied Tax Rate: {applied_rate_percent:.4f}% (as decimal: {applied_rate_decimal})
- Applied Tax Amount: ${line_item.tax_amount}

Please determine:
1. Is the tax rate applied to this item correct according to {state_code} state tax law?
2. What is the expected tax rate for this type of item in {state_code}{jurisdiction_text}? (Provide as a decimal, e.g., 0.0825 for 8.25%)
3. Provide your confidence level (0.0 to 1.0) in your determination
4. Explain your reasoning based on the relevant tax laws

IMPORTANT: 
- The applied tax rate shown above is {applied_rate_percent:.4f}% (NOT 0% - please use the exact value shown)
- Compare the applied rate ({applied_rate_percent:.4f}%) to the expected rate for this item type
- Set is_correct to true ONLY if the applied rate matches the expected rate (within 0.0001 tolerance)

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
    
    def verify_line_item_tax(self, line_item: InvoiceLineItem, state_code: str, jurisdiction: str = '') -> Dict[str, Any]:
        """
        Verify if tax applied to a line item is correct using Bedrock KB.
        
        Args:
            line_item: InvoiceLineItem instance
            state_code: State code
            jurisdiction: Optional jurisdiction
            
        Returns:
            Dictionary with verification results including:
            - is_correct: bool
            - expected_tax_rate: Decimal
            - confidence_score: Decimal
            - reasoning: str
            - kb_response: dict (full KB response)
        """
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
        
        # Build prompt
        prompt = self._build_tax_verification_prompt(line_item, state_code, jurisdiction)
        
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
            
            # Validate: If expected and applied rates match (within tolerance), automatically set is_correct to true
            applied_rate = Decimal(str(line_item.tax_rate))
            expected_rate = verification['expected_tax_rate']
            tolerance = Decimal('0.0001')  # Allow small floating point differences
            
            if abs(applied_rate - expected_rate) <= tolerance:
                # Rates match - override KB's is_correct if it's wrong
                if not verification['is_correct']:
                    logger.info(f"Auto-correcting is_correct: rates match (applied={applied_rate}, expected={expected_rate})")
                    verification['is_correct'] = True
                    # Update reasoning to note the correction
                    if "applied tax rate of 0%" in verification['reasoning'].lower():
                        verification['reasoning'] = f"[Auto-corrected] The applied tax rate ({applied_rate * 100:.4f}%) matches the expected rate ({expected_rate * 100:.4f}%). " + verification['reasoning']
            
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
                invoice.jurisdiction
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
        total_expected_tax = sum(
            Decimal(str(v['expected_tax_rate'])) * line_item.line_total
            for v, line_item in zip(verifications, invoice.line_items.all())
        )
        total_actual_tax = sum(line_item.tax_amount for line_item in invoice.line_items.all())
        
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

