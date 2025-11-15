<!-- 399ca0b5-8252-4bd7-a9d0-7b40f53f2cd1 687907c0-e355-41e7-b977-5d1b752800fe -->
# Bedrock Knowledge Base Tax Verification Integration

## Overview

Add a new pipeline step that queries Bedrock Knowledge Bases to verify if taxes applied to invoice line items are correct according to state-specific tax laws. The system will map states to knowledge bases, query the appropriate KB, and display detailed verification results in the UI.

## Implementation Steps

### 1. Database Models (`taxright/models.py`)

- **StateKnowledgeBase**: Model to store state-to-KB mappings
- Fields: `state_code` (CharField, unique), `knowledge_base_id` (CharField), `knowledge_base_name` (CharField), `region` (CharField), `is_active` (BooleanField), `created_at`, `updated_at`
- **LineItemTaxVerification**: Model to store per-line-item verification results
- Fields: `line_item` (ForeignKey to InvoiceLineItem), `is_correct` (BooleanField), `confidence_score` (DecimalField 0-1), `reasoning` (TextField), `expected_tax_rate` (DecimalField), `applied_tax_rate` (DecimalField), `verification_details` (JSONField), `verified_at` (DateTimeField), `created_at`, `updated_at`
- Update `TaxDetermination` model to include KB verification metadata (optional JSONField for KB query details)

### 2. Bedrock Knowledge Base Service (`taxright/services.py`)

- **BedrockKnowledgeBaseService**: New service class
- `__init__`: Initialize `bedrock-agent-runtime` client
- `get_knowledge_base_for_state(state_code)`: Query StateKnowledgeBase to get KB ID for state
- `query_knowledge_base(kb_id, query_text, model_id)`: Use `retrieve_and_generate` API to query KB
- `verify_line_item_tax(line_item, state_code)`: 
- Build query prompt with line item details (description, category, tax rate, tax amount)
- Get appropriate KB for state
- Query KB with structured prompt asking about tax correctness
- Parse response to extract: correctness, confidence, reasoning, expected rate
- Return structured verification result
- `verify_invoice_taxes(invoice)`: Process all line items for an invoice

### 3. Tax Verification Integration (`taxright/services.py`)

- Update `create_invoice_from_ocr` or create new function `verify_invoice_taxes_after_ocr`:
- After invoice is created from OCR, automatically trigger tax verification
- For each line item, call `BedrockKnowledgeBaseService.verify_line_item_tax`
- Create `LineItemTaxVerification` records for each line item
- Update or create `TaxDetermination` with aggregated results

### 4. API Endpoints (`taxright/views.py`)

- Add to `InvoiceViewSet`:
- `@action(detail=True, methods=['post'], url_path='verify-taxes')`: Manually trigger tax verification
- `@action(detail=True, methods=['get'], url_path='pipeline/tax-verification')`: Get tax verification results (replaces placeholder `pipeline/tax-db`)
- Add `LineItemTaxVerificationViewSet` for managing verification records
- Update `get_tax_determination_data` to include line-item-level verification details

### 5. Serializers (`taxright/serializers.py`)

- **StateKnowledgeBaseSerializer**: For managing KB mappings
- **LineItemTaxVerificationSerializer**: Include line item details, verification results, reasoning, confidence
- Update **TaxDeterminationSerializer**: Add `line_item_verifications` (nested serializer) and KB metadata fields

### 6. Admin Interface (`taxright/admin.py`)

- Register `StateKnowledgeBase` with admin for managing state-to-KB mappings
- Register `LineItemTaxVerification` (read-only or with filters)
- Add admin actions for bulk operations if needed

### 7. UI Updates (`taxright/templates/taxright/invoice_detail.html`)

- Update pipeline stage 2 from "Tax Database Processing" to "Tax Verification" (KB-based)
- Add section displaying line-item verification results:
- Table showing each line item with: description, applied tax rate, expected tax rate, correctness indicator, confidence score
- Expandable/collapsible reasoning for each line item
- Color coding: green (correct), red (incorrect), yellow (uncertain/low confidence)
- Update modal for pipeline stage 2 to show:
- Overall verification status
- Per-line-item breakdown with reasoning
- Confidence scores
- KB query metadata (if available)
- Add "Verify Taxes" button to manually trigger verification if not auto-triggered

### 8. Prompt Engineering

- Design structured prompt for KB queries that:
- Includes line item description/category
- Includes applied tax rate and amount
- Asks for: correctness (yes/no), confidence (0-1), reasoning, expected tax rate
- Requests JSON response format for parsing
- Handle cases where KB doesn't have information (graceful degradation)

### 9. Error Handling

- Handle missing KB mappings (state not configured)
- Handle KB query failures (network, permissions, etc.)
- Handle malformed KB responses
- Log errors appropriately

### 10. Configuration

- Add settings for default Bedrock model ID for KB queries
- Add settings for KB query timeout and retry logic
- Consider adding configuration for auto-trigger vs manual trigger

## Files to Modify

- `taxright/models.py`: Add new models
- `taxright/services.py`: Add BedrockKnowledgeBaseService and verification logic
- `taxright/views.py`: Add API endpoints
- `taxright/serializers.py`: Add new serializers
- `taxright/admin.py`: Register new models
- `taxright/templates/taxright/invoice_detail.html`: Update UI
- `taxright/urls.py`: Add new routes if needed
- `taxright/migrations/`: Create migration for new models

## Dependencies

- boto3 (already in requirements.txt)
- AWS Bedrock Agent Runtime API access
- Existing Bedrock knowledge bases created per state

## Testing Considerations

- Test with invoices from different states
- Test with missing KB mappings
- Test with line items that have various tax statuses
- Test error handling for KB query failures
- Verify UI displays all required information correctly

### To-dos

- [ ] Create database models: StateKnowledgeBase and LineItemTaxVerification in taxright/models.py
- [ ] Create BedrockKnowledgeBaseService class in taxright/services.py with KB query methods
- [ ] Implement tax verification logic that queries KB and creates LineItemTaxVerification records
- [ ] Add API endpoints for tax verification (manual trigger and results retrieval) in taxright/views.py
- [ ] Create serializers for new models in taxright/serializers.py
- [ ] Register new models in taxright/admin.py
- [ ] Update invoice_detail.html UI to display line-item verification results with reasoning and confidence scores
- [ ] Create database migration for new models
- [ ] Integrate auto-trigger of tax verification after OCR completes in invoice processing flow