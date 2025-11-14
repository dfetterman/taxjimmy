<!-- 5d6cb4bf-3b02-40a4-8cc6-89024ee1bf45 8d0f1972-8702-476f-8512-641bff22fb2a -->
# Invoice OCR Integration with Pipeline UI

## Overview

Update the `taxright/` app to accept PDF invoice uploads, process them through `invoice_ocr/`, store files in S3, extract structured data, and display a pipeline UI with three stages (OCR Processing, Tax Database Processing, Tax Determination).

## Pipeline Stages

1. **OCR Processing** - Extract invoice data using AWS Bedrock (implemented)
2. **Tax Database Processing** - Match against tax rules (placeholder, not developed)
3. **Tax Determination** - Final tax verification (placeholder, not developed)

## Implementation Plan

### 1. Update Invoice OCR Service for Structured Output

- **File**: `invoice_ocr/services.py`
- Modify the default prompt in `BedrockLLMService._prepare_prompt()` to request JSON output
- Update prompt to extract: invoice_number, date, vendor_name, total_amount, state_code, jurisdiction, line_items (description, quantity, unit_price, tax_amount, tax_rate)
- Return structured JSON instead of plain text

### 2. Create Invoice Data Parser

- **File**: `taxright/services.py` (new file)
- Create `InvoiceDataParser` class to:
- Parse JSON response from invoice_ocr
- Validate extracted data
- Map to taxright models (Invoice, InvoiceLineItem)
- Handle missing or invalid fields gracefully

### 3. Update Upload View to Process via OCR

- **File**: `taxright/views.py`
- Modify `upload_invoice()` view:
- Accept only PDF file upload (remove manual form fields)
- Save PDF to S3 via FileField (already configured)
- Create Invoice record with status='processing'
- Call `invoice_ocr` service asynchronously or synchronously
- Parse OCR response and populate Invoice + InvoiceLineItem records
- Update status to 'completed' or 'error'
- Store OCR job reference in Invoice model (add field if needed)

### 4. Add OCR Job Reference to Invoice Model

- **File**: `taxright/models.py`
- Add optional ForeignKey to `invoice_ocr.ProcessingJob` to track OCR processing
- Add field to store raw OCR response for review

### 5. Create Pipeline UI Component

- **File**: `taxright/templates/taxright/invoice_detail.html`
- Add pipeline visualization with 3 clickable bullets:
- Bullet 1: "OCR Processing" (active, shows extracted data)
- Bullet 2: "Tax Database Processing" (disabled/placeholder)
- Bullet 3: "Tax Determination" (disabled/placeholder)
- Each bullet opens a modal showing:
- Stage status
- Relevant data (OCR shows extracted text/structured data)
- Timestamps
- Error messages if any

### 6. Add Modal JavaScript

- **File**: `taxright/templates/taxright/invoice_detail.html` (in script block)
- Create modal component with:
- Click handlers for pipeline bullets
- AJAX calls to fetch stage data
- Modal display/hide functionality
- Content rendering based on stage

### 7. Create API Endpoints for Pipeline Data

- **File**: `taxright/views.py`
- Add ViewSet actions or separate views:
- `get_ocr_data(invoice_id)` - Returns OCR processing results
- `get_tax_db_data(invoice_id)` - Returns placeholder for tax DB processing
- `get_tax_determination_data(invoice_id)` - Returns tax determination data if exists

### 8. Update Upload Template

- **File**: `taxright/templates/taxright/upload.html`
- Simplify form to only accept PDF file
- Remove manual input fields (invoice_number, date, vendor_name, etc.)
- Add upload progress indicator
- Show processing status after upload

### 9. Update Serializers

- **File**: `taxright/serializers.py`
- Add fields for OCR job reference and raw OCR data
- Include pipeline stage status in InvoiceSerializer

### 10. Error Handling

- Handle OCR processing failures gracefully
- Store error messages in Invoice model
- Display errors in pipeline UI
- Allow retry of failed OCR processing

## Technical Details

### S3 Storage

- Files already configured to use S3 via django-storages
- PDF files stored in `invoices/%Y/%m/%d/` path (from Invoice model)
- Ensure S3 bucket permissions allow file uploads

### OCR Integration

- Use `invoice_ocr.services.InvoiceProcessor.process_pdf()`
- Pass PDF file path (temporary or S3)
- Parse JSON response from OCR service
- Map to taxright database models

### Pipeline UI Design

- Horizontal pipeline with 3 stages
- Active stage highlighted
- Clickable bullets open modals
- Modals show stage-specific content
- Responsive design matching existing UI

## Files to Modify

- `taxright/models.py` - Add OCR job reference field
- `taxright/views.py` - Update upload view, add pipeline API endpoints
- `taxright/serializers.py` - Add OCR-related fields
- `taxright/templates/taxright/upload.html` - Simplify upload form
- `taxright/templates/taxright/invoice_detail.html` - Add pipeline UI and modals
- `taxright/urls.py` - Add pipeline API routes
- `invoice_ocr/services.py` - Update prompt for JSON output
- `taxright/services.py` - New file for invoice data parsing

## Dependencies

- Existing: django-storages, boto3, invoice_ocr app
- No new dependencies required

### To-dos

- [ ] Update invoice_ocr service prompt to return structured JSON with invoice fields (invoice_number, date, vendor_name, total_amount, state_code, jurisdiction, line_items)
- [ ] Create taxright/services.py with InvoiceDataParser class to parse OCR JSON and map to Invoice/InvoiceLineItem models
- [ ] Add ProcessingJob ForeignKey and raw_ocr_data field to Invoice model, create migration
- [ ] Modify upload_invoice view to accept only PDF, save to S3, call OCR service, parse response, and create Invoice/InvoiceLineItem records
- [ ] Update upload.html template to show only PDF file upload field, remove manual input fields
- [ ] Add pipeline visualization with 3 clickable bullets to invoice_detail.html template
- [ ] Add modal JavaScript component to invoice_detail.html for displaying pipeline stage data
- [ ] Create API endpoints in taxright/views.py for fetching OCR data, tax DB data, and tax determination data
- [ ] Add OCR job reference and raw OCR data fields to InvoiceSerializer
- [ ] Implement error handling for OCR failures, store errors, display in pipeline UI, allow retry