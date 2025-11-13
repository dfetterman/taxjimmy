<!-- 06536095-574e-4678-a3d8-0739fa8f325d 5c23aa6a-6247-4305-b30f-9a930ef35eae -->
# LLM Invoice Processing App Plan

## Overview

Create a new Django app that provides invoice processing functionality via AWS Bedrock LLMs and AWS Textract. The app will be callable from other apps and return extracted invoice text with high configurability for different LLM models.

## App Structure

### App Name: `invoice_llm` (or as specified by user)

### Core Components

1. **Service Layer** (`invoice_llm/services.py`)

   - `InvoiceProcessor` class - Main service class for processing invoices
   - `BedrockLLMService` class - Handles AWS Bedrock interactions
   - `TextractService` class - Handles AWS Textract document processing
   - Methods:
     - `process_pdf(file_path, method='bedrock', model_id=None, **kwargs)` - Main entry point
     - `extract_with_textract(file_path)` - Extract text using Textract
     - `extract_with_bedrock(file_path, model_id, prompt_template, **config)` - Extract using Bedrock LLM

2. **Configuration Manager** (`invoice_llm/config.py`)

   - `ConfigManager` class - Reads configuration from database models
   - Methods to retrieve active model configs, processing settings
   - Helper methods to get default model, get model by ID, etc.
   - All configuration stored in database models (see Models section)

3. **Models** (`invoice_llm/models.py`)

   - `BedrockModelConfig` - Store LLM model configurations in database
     - Fields: name, model_id, region, max_tokens, temperature, top_p, is_default, is_active, prompt_template, created_at, updated_at
   - `ProcessingConfig` - Store processing settings in database
     - Fields: key (unique), value (JSONField), description, created_at, updated_at
     - Store: timeout settings, retry configuration, Textract settings, default model selection
   - `ProcessingJob` - Track processing requests (optional, for logging/auditing)
     - Fields: file_path, method, model_id, status, extracted_text, created_at, etc.

5. **Utilities** (`invoice_llm/utils.py`)

   - PDF validation
   - File handling utilities
   - Error handling and logging
   - Response formatting

6. **REST API** (Optional - `invoice_llm/views.py` and `invoice_llm/serializers.py`)

   - ViewSet for processing invoices via API
   - Endpoint: `/api/invoice-llm/process/`
   - Accepts PDF file upload, returns extracted text

## Implementation Details

### AWS Bedrock Integration

- Use boto3 `bedrock-runtime` client
- Support for both synchronous and streaming responses
- Configurable model parameters (temperature, max_tokens, top_p, etc.)
- Error handling for rate limits, timeouts, model availability

### AWS Textract Integration

- Use boto3 `textract` client
- Support for both `detect_document_text` and `analyze_document` APIs
- Handle async Textract jobs if needed
- Extract structured data (tables, forms) in addition to plain text

### Configuration System

- Django settings-based configuration
- Environment variable overrides
- Model-specific prompt templates
- Fallback model selection

### Error Handling

- Custom exceptions: `ProcessingError`, `ModelNotFoundError`, `TextractError`
- Retry logic with exponential backoff
- Logging integration with existing Django logging

## Files to Create

1. `invoice_llm/__init__.py`
2. `invoice_llm/apps.py`
3. `invoice_llm/models.py` (optional)
4. `invoice_llm/services.py` - Core processing logic
5. `invoice_llm/config.py` - Configuration classes
6. `invoice_llm/utils.py` - Utility functions
7. `invoice_llm/exceptions.py` - Custom exceptions
8. `invoice_llm/views.py` (optional - for REST API)
9. `invoice_llm/serializers.py` (optional - for REST API)
10. `invoice_llm/urls.py` (optional - for REST API)
11. `invoice_llm/admin.py` (if models are created)

## Dependencies

- boto3 (already in requirements.txt)
- Add: `boto3-stubs[bedrock,textract]` for type hints (optional)

## Integration Points

- Add `invoice_llm` to `INSTALLED_APPS` in `taxjimmy/settings.py`
- Update `taxjimmy/urls.py` to include API routes (if REST API is included)
- Can be imported and used in `taxright` app: `from invoice_llm.services import InvoiceProcessor`

## Usage Example

```python
from invoice_llm.services import InvoiceProcessor

processor = InvoiceProcessor()
# Using Bedrock
text = processor.process_pdf(
    file_path='/path/to/invoice.pdf',
    method='bedrock',
    model_id='anthropic.claude-3-sonnet-20240229-v1:0',
    temperature=0.7,
    max_tokens=4000
)
# Using Textract
text = processor.process_pdf(file_path='/path/to/invoice.pdf', method='textract')
```

### To-dos

- [ ] Create Django app structure (invoice_llm) with __init__, apps.py, admin.py
- [ ] Create config.py with BedrockModelConfig, ProcessingConfig, and model registry
- [ ] Create exceptions.py with custom exception classes
- [ ] Create utils.py with PDF validation and file handling utilities
- [ ] Implement TextractService class in services.py for AWS Textract integration
- [ ] Implement BedrockLLMService class in services.py for AWS Bedrock integration
- [ ] Implement InvoiceProcessor main class that orchestrates Textract and Bedrock services
- [ ] Add INVOICE_LLM_SETTINGS to taxjimmy/settings.py with default configurations
- [ ] Add invoice_llm to INSTALLED_APPS in taxjimmy/settings.py
- [ ] Create optional ProcessingJob model in models.py for tracking/auditing (if needed)
- [ ] Create REST API views, serializers, and URLs for processing invoices via HTTP (if needed)