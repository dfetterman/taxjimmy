"""
Service classes for invoice OCR processing using AWS Bedrock.
"""
import boto3
import json
import time
import logging
import base64
import os
from django.utils import timezone
from botocore.exceptions import ClientError, BotoCoreError
from typing import Optional, Dict, Any

from invoice_ocr.config import ConfigManager
from invoice_ocr.exceptions import (
    InvoiceProcessingError,
    BedrockError,
    ModelNotFoundError,
    PDFValidationError,
    ConfigurationError
)
from invoice_ocr.utils import validate_pdf_file, read_pdf_file, format_extracted_text
from invoice_ocr.models import ProcessingJob

logger = logging.getLogger(__name__)


class BedrockLLMService:
    """Service for processing invoices using AWS Bedrock LLMs."""
    
    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize Bedrock service.
        
        Args:
            region_name: AWS region (defaults to config or us-east-1)
        """
        self.region_name = region_name or ConfigManager.get_bedrock_region()
        try:
            self.client = boto3.client('bedrock-runtime', region_name=self.region_name)
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize Bedrock client: {str(e)}")
    
    def _prepare_prompt(self, file_text: str, prompt_template: Optional[str] = None) -> str:
        """
        Prepare the prompt for LLM processing.
        
        Args:
            file_text: Text extracted from PDF
            prompt_template: Custom prompt template (uses model default if None)
            
        Returns:
            str: Formatted prompt
        """
        if prompt_template:
            return prompt_template.format(invoice_text=file_text)
        
        # Default prompt template
        default_prompt = """You are an expert at extracting information from invoices. 
Analyze the following invoice text and extract all relevant information in a clear, structured format.

Invoice Text:
{invoice_text}

Please extract and format all key information from this invoice."""
        
        return default_prompt.format(invoice_text=file_text)
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for Converse API requirements.
        
        Converse API allows only:
        - Alphanumeric characters
        - Whitespace characters (but not more than one consecutive)
        - Hyphens
        - Parentheses
        - Square brackets
        
        Note: Dots are NOT allowed. The format is specified separately in the document object.
        
        Args:
            filename: Original filename
            
        Returns:
            str: Sanitized filename (without extension)
        """
        import re
        
        # Remove path components, keep only the filename
        filename = os.path.basename(filename)
        
        # Remove file extension (everything after the last dot)
        # Since format is specified separately, we don't need extension in name
        name_without_ext = os.path.splitext(filename)[0]
        
        # Replace invalid characters with hyphens
        # Allow ONLY: alphanumeric, whitespace, hyphens, parentheses, square brackets
        # Note: NO DOTS allowed!
        sanitized = re.sub(r'[^a-zA-Z0-9\s\-\(\)\[\]]', '-', name_without_ext)
        
        # Replace multiple consecutive whitespace with single space
        sanitized = re.sub(r'\s+', ' ', sanitized)
        
        # Replace multiple consecutive hyphens with single hyphen
        sanitized = re.sub(r'-+', '-', sanitized)
        
        # Strip leading/trailing whitespace and hyphens
        sanitized = sanitized.strip(' -')
        
        # If empty after sanitization, use default
        if not sanitized:
            sanitized = "invoice"
        
        return sanitized
    
    def _invoke_model(self, model_id: str, prompt: str, config: Dict[str, Any], 
                     pdf_bytes: Optional[bytes] = None, pdf_filename: Optional[str] = None) -> tuple[str, Dict[str, int]]:
        """
        Invoke Bedrock model with the given prompt.
        
        Args:
            model_id: AWS Bedrock model ID
            prompt: Prompt text
            config: Model configuration (temperature, max_tokens, etc.)
            pdf_bytes: Optional PDF file bytes for direct multimodal processing (Claude 3+)
                      Uses Converse API for direct PDF attachment
            pdf_filename: Optional filename for the PDF (defaults to "invoice.pdf" if not provided)
            
        Returns:
            tuple: (response_text, token_usage_dict)
                - response_text: Model response text
                - token_usage_dict: Dictionary with 'inputTokens', 'outputTokens', 'totalTokens'
            
        Raises:
            BedrockError: If invocation fails
        """
        # Use Converse API for direct PDF processing (supports PDF, DOCX, TXT, Markdown, CSV)
        if pdf_bytes:
            try:
                # Converse API supports direct PDF attachment
                # Note: bytes should be raw bytes, not base64 encoded
                
                # Sanitize filename to meet Converse API requirements
                filename = self._sanitize_filename(pdf_filename) if pdf_filename else "invoice"
                
                # Build message content with PDF attachment
                # Order matters: document first, then text instruction
                content = [
                    {
                        "document": {
                            "format": "pdf",
                            "name": filename,
                            "source": {
                                "bytes": pdf_bytes
                            }
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
                
                # Prepare Converse API request
                converse_kwargs = {
                    "modelId": model_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    "inferenceConfig": {
                        "maxTokens": config.get('max_tokens', 4096),
                        "temperature": config.get('temperature', 0.7),
                        "topP": config.get('top_p', 0.9),
                    }
                }
                
                response = self.client.converse(**converse_kwargs)
                
                # Extract text from Converse API response
                text_result = None
                if 'output' in response and 'message' in response['output']:
                    message = response['output']['message']
                    if 'content' in message:
                        # Converse API returns content as a list
                        text_parts = []
                        for content_item in message['content']:
                            if 'text' in content_item:
                                text_parts.append(content_item['text'])
                        text_result = '\n'.join(text_parts)
                    else:
                        raise BedrockError("Unexpected Converse API response format - no content")
                else:
                    raise BedrockError("Unexpected Converse API response format")
                
                # Extract token usage from Converse API response
                token_usage = {
                    'inputTokens': 0,
                    'outputTokens': 0,
                    'totalTokens': 0
                }
                if 'usage' in response:
                    usage = response['usage']
                    token_usage['inputTokens'] = usage.get('inputTokens', 0)
                    token_usage['outputTokens'] = usage.get('outputTokens', 0)
                    token_usage['totalTokens'] = usage.get('totalTokens', 0)
                
                return text_result, token_usage
                    
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', str(e))
                raise BedrockError(f"AWS Bedrock Converse API error ({error_code}): {error_message}")
            except Exception as e:
                raise BedrockError(f"Error using Converse API: {str(e)}")
        
        # Fall back to invoke_model for text-only processing
        # Prepare request body based on model provider
        if 'claude' in model_id.lower():
            # Anthropic Claude format
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": config.get('max_tokens', 4096),
                "temperature": config.get('temperature', 0.7),
                "top_p": config.get('top_p', 0.9),
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        elif 'llama' in model_id.lower():
            # Meta Llama format
            body = {
                "prompt": prompt,
                "max_gen_len": config.get('max_tokens', 4096),
                "temperature": config.get('temperature', 0.7),
                "top_p": config.get('top_p', 0.9),
            }
        elif 'titan' in model_id.lower():
            # Amazon Titan format
            body = {
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": config.get('max_tokens', 4096),
                    "temperature": config.get('temperature', 0.7),
                    "topP": config.get('top_p', 0.9),
                }
            }
        else:
            # Generic format - try Anthropic format as default
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": config.get('max_tokens', 4096),
                "temperature": config.get('temperature', 0.7),
                "top_p": config.get('top_p', 0.9),
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        
        try:
            response = self.client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType='application/json',
                accept='application/json'
            )
            
            response_body = json.loads(response['body'].read())
            
            # Extract text based on model provider
            text_result = None
            if 'claude' in model_id.lower():
                # Anthropic Claude response format
                if 'content' in response_body and len(response_body['content']) > 0:
                    text_result = response_body['content'][0]['text']
                else:
                    raise BedrockError("Unexpected Claude response format")
            elif 'llama' in model_id.lower():
                # Meta Llama response format
                text_result = response_body.get('generation', '')
            elif 'titan' in model_id.lower():
                # Amazon Titan response format
                results = response_body.get('results', [])
                if results:
                    text_result = results[0].get('outputText', '')
                else:
                    text_result = ''
            else:
                # Try to extract text from generic response
                if 'content' in response_body:
                    if isinstance(response_body['content'], list) and len(response_body['content']) > 0:
                        text_result = response_body['content'][0].get('text', '')
                if text_result is None:
                    text_result = str(response_body)
            
            # Extract token usage (if available in response metadata)
            # Note: invoke_model may not always return usage info in the same format
            token_usage = {
                'inputTokens': 0,
                'outputTokens': 0,
                'totalTokens': 0
            }
            
            # Check for usage in response metadata (varies by model)
            if 'usage' in response_body:
                usage = response_body['usage']
                token_usage['inputTokens'] = usage.get('inputTokens', usage.get('input_tokens', 0))
                token_usage['outputTokens'] = usage.get('outputTokens', usage.get('output_tokens', 0))
                token_usage['totalTokens'] = usage.get('totalTokens', usage.get('total_tokens', 0))
            elif 'input_tokens' in response_body or 'output_tokens' in response_body:
                # Some models return tokens at top level
                token_usage['inputTokens'] = response_body.get('input_tokens', 0)
                token_usage['outputTokens'] = response_body.get('output_tokens', 0)
                token_usage['totalTokens'] = token_usage['inputTokens'] + token_usage['outputTokens']
            
            return text_result, token_usage
                
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            raise BedrockError(f"AWS Bedrock error ({error_code}): {error_message}")
        except BotoCoreError as e:
            raise BedrockError(f"Boto3 error: {str(e)}")
        except json.JSONDecodeError as e:
            raise BedrockError(f"Failed to parse Bedrock response: {str(e)}")
        except Exception as e:
            raise BedrockError(f"Unexpected error during Bedrock processing: {str(e)}")
    
    def _calculate_cost(self, token_usage: Dict[str, int], input_token_cost: float, output_token_cost: float) -> Dict[str, float]:
        """
        Calculate cost based on token usage and model pricing.
        
        Args:
            token_usage: Dictionary with 'inputTokens', 'outputTokens', 'totalTokens'
            input_token_cost: Cost per 1K input tokens
            output_token_cost: Cost per 1K output tokens
            
        Returns:
            Dictionary with 'inputCost', 'outputCost', 'totalCost'
        """
        input_tokens = token_usage.get('inputTokens', 0)
        output_tokens = token_usage.get('outputTokens', 0)
        
        # Convert Decimal to float if needed
        input_cost_per_thousand = float(input_token_cost) if input_token_cost else 0.0
        output_cost_per_thousand = float(output_token_cost) if output_token_cost else 0.0
        
        # Calculate costs (cost per thousand tokens)
        input_cost = (input_tokens / 1_000) * input_cost_per_thousand
        output_cost = (output_tokens / 1_000) * output_cost_per_thousand
        total_cost = input_cost + output_cost
        
        return {
            'inputCost': round(input_cost, 8),
            'outputCost': round(output_cost, 8),
            'totalCost': round(total_cost, 8)
        }
    
    def process_invoice(self, file_path: str, model_id: Optional[str] = None, 
                       prompt_template: Optional[str] = None,
                       **kwargs) -> tuple[str, Dict[str, Any]]:
        """
        Process invoice using Bedrock LLM with direct PDF processing.
        
        Args:
            file_path: Path to PDF file
            model_id: Model ID to use (defaults to configured default)
            prompt_template: Custom prompt template
            **kwargs: Additional model parameters (temperature, max_tokens, etc.)
            
        Returns:
            tuple: (processed_text, usage_dict)
                - processed_text: Processed invoice text
                - usage_dict: Dictionary with 'inputTokens', 'outputTokens', 'totalTokens', 
                             'inputCost', 'outputCost', 'totalCost'
            
        Raises:
            BedrockError: If processing fails
        """
        validate_pdf_file(file_path)
        
        # Get model configuration
        if model_id:
            model_config = ConfigManager.get_model_by_id(model_id)
        else:
            model_config = ConfigManager.get_default_model()
            model_id = model_config.model_id
        
        # Prepare model configuration
        config = {
            'max_tokens': kwargs.get('max_tokens', model_config.max_tokens),
            'temperature': kwargs.get('temperature', model_config.temperature),
            'top_p': kwargs.get('top_p', model_config.top_p),
        }
        
        # Get prompt template
        if not prompt_template:
            prompt_template = model_config.prompt_template
        
        # Determine if model supports direct PDF processing (multimodal)
        # Claude 3+ and Amazon Nova models support direct PDF/image processing via Converse API
        is_claude_multimodal = 'claude' in model_id.lower() and ('claude-3' in model_id.lower() or 'claude-4' in model_id.lower())
        is_nova = 'nova' in model_id.lower()
        supports_multimodal = is_claude_multimodal or is_nova
        
        if supports_multimodal:
            # Read PDF bytes for direct processing
            pdf_bytes = read_pdf_file(file_path)
            
            # Extract filename from file path
            pdf_filename = os.path.basename(file_path)
            
            # Prepare prompt for direct PDF processing
            if prompt_template:
                prompt = prompt_template.format(invoice_text="[PDF document will be processed directly]")
            else:
                prompt = """You are an expert at extracting information from invoices. 
Analyze the following invoice PDF and extract all relevant information in a structured JSON format.

Extract the following information and return it as valid JSON only (no markdown, no code blocks, just the JSON object):

{
  "invoice_number": "string (invoice number or ID)",
  "date": "YYYY-MM-DD (invoice date)",
  "vendor_name": "string (vendor or supplier name)",
  "total_amount": "decimal number (total invoice amount)",
  "state_code": "string (2-letter US state code, e.g., CA, NY)",
  "jurisdiction": "string (county, city, or special district if applicable, empty string if not)",
  "line_items": [
    {
      "description": "string (item description)",
      "quantity": "decimal number",
      "unit_price": "decimal number",
      "line_total": "decimal number (quantity * unit_price)",
      "tax_amount": "decimal number (tax for this line item)",
      "tax_rate": "decimal number (tax rate as decimal, e.g., 0.0825 for 8.25%)",
      "tax_status": "string (one of: 'taxable', 'exempt', 'unknown')"
    }
  ]
}

Important:
- Return ONLY valid JSON, no additional text or explanation
- If a field cannot be determined, use empty string for strings, 0 for numbers, or empty array for line_items
- Dates must be in YYYY-MM-DD format
- All amounts should be decimal numbers (strings in JSON)
- State code should be 2-letter uppercase US state code
- If jurisdiction is not found, use empty string"""
            
            # Invoke model with PDF bytes and filename
            result, token_usage = self._invoke_model(model_id, prompt, config, pdf_bytes=pdf_bytes, pdf_filename=pdf_filename)
        else:
            # Model doesn't support multimodal - raise error
            raise BedrockError(f"Model {model_id} does not support direct PDF processing. Please use a Claude 3+ or Amazon Nova model.")
        
        # Calculate costs based on model pricing
        cost_info = self._calculate_cost(
            token_usage,
            model_config.input_token_cost,
            model_config.output_token_cost
        )
        
        # Combine token usage and cost information
        usage_info = {
            **token_usage,
            **cost_info
        }
        
        # Try to extract JSON from the response (might be wrapped in markdown code blocks)
        json_result = self._extract_json_from_response(result)
        formatted_result = json_result if json_result else format_extracted_text(result)
        return formatted_result, usage_info
    
    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """
        Extract JSON from response text, handling markdown code blocks.
        
        Args:
            text: Response text that may contain JSON
            
        Returns:
            str: Extracted JSON string, or None if not found
        """
        import re
        
        # Try to find JSON in markdown code blocks
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Try to find JSON object directly
        json_pattern = r'(\{.*\})'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            try:
                # Validate it's valid JSON
                json.loads(match.group(1))
                return match.group(1).strip()
            except json.JSONDecodeError:
                pass
        
        # If no JSON found, return None
        return None


class InvoiceProcessor:
    """Main service class for processing invoices using OCR via AWS Bedrock."""
    
    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize invoice processor.
        
        Args:
            region_name: AWS region (defaults to config)
        """
        self.region_name = region_name
        self.bedrock_service = BedrockLLMService(region_name=region_name)
    
    def process_pdf(self, file_path: str, method: str = 'bedrock', 
                   model_id: Optional[str] = None,
                   create_job: bool = True,
                   **kwargs) -> str:
        """
        Main entry point for processing PDF invoices.
        
        Args:
            file_path: Path to PDF file
            method: Processing method (only 'bedrock' is supported)
            model_id: Model ID for Bedrock (optional, uses default if not specified)
            create_job: Whether to create a ProcessingJob record
            **kwargs: Additional parameters (temperature, max_tokens, prompt_template, etc.)
            
        Returns:
            str: Extracted/processed invoice text
            
        Raises:
            InvoiceProcessingError: If processing fails
        """
        if method != 'bedrock':
            raise InvoiceProcessingError(f"Only 'bedrock' method is supported. Received: {method}")
        
        job = None
        if create_job:
            job = ProcessingJob.objects.create(
                file_path=file_path,
                method=method,
                model_id=model_id,
                status='processing'
            )
        
        try:
            result, usage_info = self.bedrock_service.process_invoice(
                file_path,
                model_id=model_id,
                prompt_template=kwargs.get('prompt_template'),
                **{k: v for k, v in kwargs.items() if k not in ['prompt_template']}
            )
            # Store token usage and cost in job metadata if job exists
            if job:
                job.metadata = job.metadata or {}
                job.metadata['usage'] = usage_info
                job.save()
            
            if job:
                job.status = 'completed'
                job.extracted_text = result
                job.completed_at = timezone.now()
                job.save()
            
            return result
            
        except Exception as e:
            if job:
                job.status = 'failed'
                job.error_message = str(e)
                job.save()
            raise
    
    def extract_with_bedrock(self, file_path: str, model_id: Optional[str] = None,
                            prompt_template: Optional[str] = None, **config) -> str:
        """
        Extract text using Bedrock LLM.
        
        Args:
            file_path: Path to PDF file
            model_id: Model ID (optional)
            prompt_template: Custom prompt template (optional)
            **config: Additional model configuration
            
        Returns:
            str: Processed text
        """
        result, _ = self.bedrock_service.process_invoice(
            file_path,
            model_id=model_id,
            prompt_template=prompt_template,
            **config
        )
        return result
