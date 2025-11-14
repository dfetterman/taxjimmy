"""
Management command to test invoice OCR processing via AWS Bedrock.

Usage:
    # Basic usage with default model
    python manage.py test_invoice_processing /path/to/invoice.pdf
    
    # Use specific Claude 3 model
    python manage.py test_invoice_processing /path/to/invoice.pdf --model-id anthropic.claude-3-sonnet-20240229-v1:0
"""
import os
import time
from django.core.management.base import BaseCommand, CommandError
from invoice_ocr.services import InvoiceProcessor
from invoice_ocr.config import ConfigManager
from invoice_ocr.exceptions import (
    InvoiceProcessingError,
    ModelNotFoundError,
    ConfigurationError
)


class Command(BaseCommand):
    help = 'Test invoice processing via AWS Bedrock model'

    def add_arguments(self, parser):
        parser.add_argument(
            'pdf_path',
            type=str,
            help='Path to the PDF invoice file to process'
        )
        parser.add_argument(
            '--model-id',
            type=str,
            default=None,
            help='AWS Bedrock model ID to use (e.g., anthropic.claude-3-sonnet-20240229-v1:0). If not specified, uses default model.'
        )
        parser.add_argument(
            '--temperature',
            type=float,
            default=None,
            help='Temperature for model generation (0.0-1.0). Overrides model default.'
        )
        parser.add_argument(
            '--max-tokens',
            type=int,
            default=None,
            help='Maximum tokens in response. Overrides model default.'
        )
        parser.add_argument(
            '--no-job',
            action='store_true',
            help='Do not create a ProcessingJob record'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed processing information'
        )

    def handle(self, *args, **options):
        pdf_path = options['pdf_path']
        model_id = options.get('model_id')
        create_job = not options.get('no_job', False)
        verbose = options.get('verbose', False)
        
        # Validate PDF file exists
        if not os.path.exists(pdf_path):
            raise CommandError(f'PDF file not found: {pdf_path}')
        
        if not pdf_path.lower().endswith('.pdf'):
            raise CommandError(f'File does not appear to be a PDF: {pdf_path}')
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Testing Invoice Processing ==='))
        self.stdout.write(f'PDF File: {pdf_path}')
        self.stdout.write(f'File Size: {os.path.getsize(pdf_path) / 1024:.2f} KB')
        
        # Display model information
        try:
            if model_id:
                model_config = ConfigManager.get_model_by_id(model_id)
                self.stdout.write(f'Model: {model_config.name} ({model_config.model_id})')
            else:
                model_config = ConfigManager.get_default_model()
                model_id = model_config.model_id
                self.stdout.write(f'Model: {model_config.name} ({model_config.model_id}) [default]')
            
            if verbose:
                self.stdout.write(f'  Region: {model_config.region}')
                self.stdout.write(f'  Max Tokens: {model_config.max_tokens}')
                self.stdout.write(f'  Temperature: {model_config.temperature}')
                self.stdout.write(f'  Top P: {model_config.top_p}')
        except ModelNotFoundError as e:
            raise CommandError(f'Model configuration error: {str(e)}')
        except ConfigurationError as e:
            raise CommandError(f'Configuration error: {str(e)}')
        
        # Check if model supports direct PDF processing
        # Claude 3+ and Amazon Nova models support direct PDF/image processing via Converse API
        is_claude_multimodal = 'claude' in model_id.lower() and ('claude-3' in model_id.lower() or 'claude-4' in model_id.lower())
        is_nova = 'nova' in model_id.lower()
        supports_multimodal = is_claude_multimodal or is_nova
        
        if supports_multimodal:
            self.stdout.write(f'Method: Bedrock (Direct PDF processing)')
            if is_nova:
                self.stdout.write(self.style.SUCCESS('  → Using Amazon Nova multimodal capabilities'))
            else:
                self.stdout.write(self.style.SUCCESS('  → Using Claude multimodal capabilities'))
        else:
            self.stdout.write(self.style.WARNING(f'Model {model_id} may not support direct PDF processing'))
        self.stdout.write('')
        
        # Prepare processing parameters
        process_kwargs = {}
        
        if options.get('temperature') is not None:
            process_kwargs['temperature'] = options['temperature']
            if verbose:
                self.stdout.write(f'  Override Temperature: {options["temperature"]}')
        
        if options.get('max_tokens') is not None:
            process_kwargs['max_tokens'] = options['max_tokens']
            if verbose:
                self.stdout.write(f'  Override Max Tokens: {options["max_tokens"]}')
        
        # Process the invoice
        self.stdout.write(self.style.WARNING('Starting processing...'))
        start_time = time.time()
        
        try:
            processor = InvoiceProcessor()
            result = processor.process_pdf(
                file_path=pdf_path,
                method='bedrock',
                model_id=model_id,
                create_job=create_job,
                **process_kwargs
            )
            
            elapsed_time = time.time() - start_time
            
            self.stdout.write(self.style.SUCCESS(f'\n✓ Processing completed in {elapsed_time:.2f} seconds'))
            self.stdout.write('')
            
            # Display results
            self.stdout.write(self.style.SUCCESS('=== Processing Results ==='))
            self.stdout.write('')
            self.stdout.write(result)
            self.stdout.write('')
            
            # Get job information if created
            job = None
            if create_job:
                from invoice_ocr.models import ProcessingJob
                job = ProcessingJob.objects.filter(
                    file_path=pdf_path,
                    method='bedrock'
                ).order_by('-created_at').first()
                
                if job:
                    self.stdout.write(self.style.SUCCESS('=== Processing Job Record ==='))
                    self.stdout.write(f'Job ID: {job.id}')
                    self.stdout.write(f'Status: {job.status}')
                    self.stdout.write(f'Created: {job.created_at}')
                    if job.completed_at:
                        self.stdout.write(f'Completed: {job.completed_at}')
                        duration = (job.completed_at - job.created_at).total_seconds()
                        self.stdout.write(f'Duration: {duration:.2f} seconds')
                    
                    # Display token usage and cost if available
                    if job.metadata and 'usage' in job.metadata:
                        usage = job.metadata['usage']
                        self.stdout.write('')
                        self.stdout.write(self.style.SUCCESS('=== Token Usage & Cost ==='))
                        self.stdout.write(f'Input Tokens: {usage.get("inputTokens", 0):,}')
                        self.stdout.write(f'Output Tokens: {usage.get("outputTokens", 0):,}')
                        self.stdout.write(f'Total Tokens: {usage.get("totalTokens", 0):,}')
                        if usage.get("inputCost") is not None or usage.get("outputCost") is not None:
                            self.stdout.write('')
                            self.stdout.write(f'Input Cost: ${usage.get("inputCost", 0):.8f}')
                            self.stdout.write(f'Output Cost: ${usage.get("outputCost", 0):.8f}')
                            self.stdout.write(f'Total Cost: ${usage.get("totalCost", 0):.8f}')
                    
                    if job.error_message:
                        self.stdout.write(self.style.ERROR(f'Error: {job.error_message}'))
                    self.stdout.write('')
            
            # Summary
            self.stdout.write(self.style.SUCCESS('=== Summary ==='))
            self.stdout.write(f'✓ Successfully processed invoice')
            self.stdout.write(f'✓ Extracted text length: {len(result)} characters')
            self.stdout.write(f'✓ Processing time: {elapsed_time:.2f} seconds')
            
            # Display token usage and cost in summary if available
            if job and job.metadata and 'usage' in job.metadata:
                usage = job.metadata['usage']
                self.stdout.write(f'✓ Input Tokens: {usage.get("inputTokens", 0):,}')
                self.stdout.write(f'✓ Output Tokens: {usage.get("outputTokens", 0):,}')
                self.stdout.write(f'✓ Total Tokens: {usage.get("totalTokens", 0):,}')
                if usage.get("totalCost") is not None:
                    self.stdout.write(f'✓ Total Cost: ${usage.get("totalCost", 0):.8f}')
            
        except InvoiceProcessingError as e:
            elapsed_time = time.time() - start_time
            self.stdout.write(self.style.ERROR(f'\n✗ Processing failed after {elapsed_time:.2f} seconds'))
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            raise CommandError(f'Invoice processing failed: {str(e)}')
        except Exception as e:
            elapsed_time = time.time() - start_time
            self.stdout.write(self.style.ERROR(f'\n✗ Unexpected error after {elapsed_time:.2f} seconds'))
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            raise CommandError(f'Unexpected error: {str(e)}')

