"""
Service classes for invoice processing using AWS Bedrock and Textract.
"""
import boto3
import json
import time
import logging
from django.utils import timezone
from botocore.exceptions import ClientError, BotoCoreError
from typing import Optional, Dict, Any

from invoice_llm.config import ConfigManager
from invoice_llm.exceptions import (
    InvoiceProcessingError,
    TextractError,
    BedrockError,
    ModelNotFoundError,
    PDFValidationError,
    ConfigurationError
)
from invoice_llm.utils import validate_pdf_file, read_pdf_file, format_extracted_text
from invoice_llm.models import ProcessingJob

logger = logging.getLogger(__name__)


class TextractService:
    """Service for processing invoices using AWS Textract."""
    
    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize Textract service.
        
        Args:
            region_name: AWS region (defaults to config or us-east-1)
        """
        self.region_name = region_name or ConfigManager.get_bedrock_region()
        try:
            self.client = boto3.client('textract', region_name=self.region_name)
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize Textract client: {str(e)}")
    
    def extract_text(self, file_path: str, use_analyze: bool = False) -> str:
        """
        Extract text from PDF using AWS Textract.
        
        Args:
            file_path: Path to PDF file
            use_analyze: Whether to use analyze_document (for tables/forms) or detect_document_text
            
        Returns:
            str: Extracted text
            
        Raises:
            TextractError: If extraction fails
        """
        validate_pdf_file(file_path)
        
        file_bytes = read_pdf_file(file_path)
        textract_config = ConfigManager.get_textract_config()
        
        try:
            if use_analyze or textract_config.get('use_analyze_document', False):
                # Use analyze_document for better table and form extraction
                feature_types = textract_config.get('feature_types', ['TABLES', 'FORMS'])
                response = self.client.analyze_document(
                    Document={'Bytes': file_bytes},
                    FeatureTypes=feature_types
                )
            else:
                # Use detect_document_text for simple text extraction
                response = self.client.detect_document_text(
                    Document={'Bytes': file_bytes}
                )
            
            # Extract text from blocks
            text_blocks = []
            if 'Blocks' in response:
                for block in response['Blocks']:
                    if block['BlockType'] == 'LINE':
                        text_blocks.append(block.get('Text', ''))
            
            extracted_text = '\n'.join(text_blocks)
            return format_extracted_text(extracted_text)
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            raise TextractError(f"AWS Textract error ({error_code}): {error_message}")
        except BotoCoreError as e:
            raise TextractError(f"Boto3 error: {str(e)}")
        except Exception as e:
            raise TextractError(f"Unexpected error during Textract processing: {str(e)}")


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
            file_text: Text extracted from PDF (via Textract or other method)
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
    
    def _invoke_model(self, model_id: str, prompt: str, config: Dict[str, Any]) -> str:
        """
        Invoke Bedrock model with the given prompt.
        
        Args:
            model_id: AWS Bedrock model ID
            prompt: Prompt text
            config: Model configuration (temperature, max_tokens, etc.)
            
        Returns:
            str: Model response text
            
        Raises:
            BedrockError: If invocation fails
        """
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
            if 'claude' in model_id.lower():
                # Anthropic Claude response format
                if 'content' in response_body and len(response_body['content']) > 0:
                    return response_body['content'][0]['text']
                else:
                    raise BedrockError("Unexpected Claude response format")
            elif 'llama' in model_id.lower():
                # Meta Llama response format
                return response_body.get('generation', '')
            elif 'titan' in model_id.lower():
                # Amazon Titan response format
                results = response_body.get('results', [])
                if results:
                    return results[0].get('outputText', '')
                return ''
            else:
                # Try to extract text from generic response
                if 'content' in response_body:
                    if isinstance(response_body['content'], list) and len(response_body['content']) > 0:
                        return response_body['content'][0].get('text', '')
                return str(response_body)
                
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
    
    def process_invoice(self, file_path: str, model_id: Optional[str] = None, 
                       prompt_template: Optional[str] = None,
                       use_textract_first: bool = True,
                       **kwargs) -> str:
        """
        Process invoice using Bedrock LLM.
        
        Args:
            file_path: Path to PDF file
            model_id: Model ID to use (defaults to configured default)
            prompt_template: Custom prompt template
            use_textract_first: Whether to extract text with Textract first
            **kwargs: Additional model parameters (temperature, max_tokens, etc.)
            
        Returns:
            str: Processed invoice text
            
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
        
        # Extract text from PDF first (using Textract or direct read)
        if use_textract_first:
            try:
                textract_service = TextractService(region_name=self.region_name)
                file_text = textract_service.extract_text(file_path, use_analyze=False)
            except Exception as e:
                logger.warning(f"Textract extraction failed, using direct PDF read: {str(e)}")
                # Fallback: try to read as text (won't work for binary PDFs, but worth trying)
                file_text = f"PDF file: {file_path}"
        else:
            # For now, we still need Textract to extract text from PDF
            # In future, could add direct PDF parsing
            textract_service = TextractService(region_name=self.region_name)
            file_text = textract_service.extract_text(file_path, use_analyze=False)
        
        # Prepare prompt
        prompt = self._prepare_prompt(file_text, prompt_template)
        
        # Invoke model
        result = self._invoke_model(model_id, prompt, config)
        
        return format_extracted_text(result)


class InvoiceProcessor:
    """Main service class for processing invoices."""
    
    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize invoice processor.
        
        Args:
            region_name: AWS region (defaults to config)
        """
        self.region_name = region_name
        self.textract_service = TextractService(region_name=region_name)
        self.bedrock_service = BedrockLLMService(region_name=region_name)
    
    def process_pdf(self, file_path: str, method: str = 'bedrock', 
                   model_id: Optional[str] = None,
                   create_job: bool = True,
                   **kwargs) -> str:
        """
        Main entry point for processing PDF invoices.
        
        Args:
            file_path: Path to PDF file
            method: Processing method ('bedrock' or 'textract')
            model_id: Model ID for Bedrock (optional, uses default if not specified)
            create_job: Whether to create a ProcessingJob record
            **kwargs: Additional parameters (temperature, max_tokens, prompt_template, etc.)
            
        Returns:
            str: Extracted/processed invoice text
            
        Raises:
            InvoiceProcessingError: If processing fails
        """
        job = None
        if create_job:
            job = ProcessingJob.objects.create(
                file_path=file_path,
                method=method,
                model_id=model_id,
                status='processing'
            )
        
        try:
            if method == 'textract':
                result = self.textract_service.extract_text(
                    file_path,
                    use_analyze=kwargs.get('use_analyze', False)
                )
            elif method == 'bedrock':
                result = self.bedrock_service.process_invoice(
                    file_path,
                    model_id=model_id,
                    prompt_template=kwargs.get('prompt_template'),
                    use_textract_first=kwargs.get('use_textract_first', True),
                    **{k: v for k, v in kwargs.items() if k not in ['prompt_template', 'use_textract_first', 'use_analyze']}
                )
            else:
                raise InvoiceProcessingError(f"Unknown processing method: {method}")
            
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
    
    def extract_with_textract(self, file_path: str, use_analyze: bool = False) -> str:
        """
        Extract text using Textract only.
        
        Args:
            file_path: Path to PDF file
            use_analyze: Whether to use analyze_document
            
        Returns:
            str: Extracted text
        """
        return self.textract_service.extract_text(file_path, use_analyze=use_analyze)
    
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
        return self.bedrock_service.process_invoice(
            file_path,
            model_id=model_id,
            prompt_template=prompt_template,
            **config
        )
