<!-- ebd27050-1791-4e85-bbfb-685ea2f83a6e bda125e1-8c7e-4456-a5f3-275114848403 -->
# LLM Cost Tracking Implementation

## Overview

Add comprehensive cost tracking for LLM interactions at both the invoice (OCR) and line item (KB verification) levels, with automatic total cost calculation.

## Database Schema Changes

### Invoice Model (`taxright/models.py`)

Add fields for OCR token tracking:

- `ocr_input_tokens` (IntegerField, default=0)
- `ocr_output_tokens` (IntegerField, default=0) 
- `ocr_total_tokens` (IntegerField, default=0) - calculated field
- `ocr_input_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)
- `ocr_output_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)
- `ocr_total_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)
- `total_llm_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00) - OCR cost + sum of all line item costs

### InvoiceLineItem Model (`taxright/models.py`)

Add fields for KB verification token tracking:

- `kb_input_tokens` (IntegerField, default=0)
- `kb_output_tokens` (IntegerField, default=0)
- `kb_total_tokens` (IntegerField, default=0) - calculated field
- `kb_input_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)
- `kb_output_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)
- `kb_total_cost` (DecimalField, max_digits=12, decimal_places=8, default=0.00)

## Service Layer Updates

### OCR Processing (`invoice_ocr/services.py`)

Update `InvoiceProcessor.process_pdf()` to:

- Extract token usage from `usage_info` returned by `BedrockLLMService.process_invoice()`
- Save token counts and costs to Invoice model when invoice is created/updated
- Update `create_invoice_from_ocr()` in `taxright/services.py` to accept and store OCR cost data

### KB Verification (`taxright/services.py`)

Add token estimation utility:

- Create `_estimate_tokens()` method in `BedrockKnowledgeBaseService` to estimate tokens from text length (rough estimate: ~4 chars per token for English)
- Update `query_knowledge_base()` to return estimated token usage
- Update `verify_line_item_tax()` to:
- Estimate input tokens from prompt length
- Estimate output tokens from response length
- Get model pricing from `BedrockModelConfig` or `StateKnowledgeBase` cost fields
- Calculate costs using same formula as OCR (`(tokens / 1000) * cost_per_1k`)
- Save token counts and costs to `InvoiceLineItem` when verification is performed
- Update `verify_invoice_taxes()` to recalculate `total_llm_cost` on Invoice after all line items are verified

## Migration

**Note:** No Django migrations will be created. Any previous migrations related to cost tracking should be ignored. Database schema changes will be handled manually or through existing migration processes.

## Additional Updates

- Update `taxright/serializers.py` to include new cost fields in serializers
- Update `taxright/admin.py` to display cost fields in admin interface
- Ensure `total_llm_cost` is recalculated whenever line items are added/updated/deleted

## Implementation Notes

- Token estimation uses simple character-based approximation (~4 chars/token) since exact tokenization requires model-specific tokenizers
- Cost calculation uses the same pattern as existing OCR cost calculation: `(tokens / 1000) * cost_per_1k_tokens`
- Model pricing should be retrieved from `BedrockModelConfig` for KB queries (default model is Claude 3 Sonnet)
- All cost fields use DecimalField with 8 decimal places for precision

### To-dos

- [ ] Add OCR token count and cost fields to Invoice model (ocr_input_tokens, ocr_output_tokens, ocr_total_tokens, ocr_input_cost, ocr_output_cost, ocr_total_cost, total_llm_cost)
- [ ] Add KB verification token count and cost fields to InvoiceLineItem model (kb_input_tokens, kb_output_tokens, kb_total_tokens, kb_input_cost, kb_output_cost, kb_total_cost)
- [ ] Add token estimation utility function to BedrockKnowledgeBaseService that estimates tokens from text length (~4 chars per token)
- [ ] Update invoice_ocr/services.py and taxright/services.py to save OCR token counts and costs to Invoice model after processing
- [ ] Update BedrockKnowledgeBaseService to estimate tokens, calculate costs, and save to InvoiceLineItem during tax verification
- [ ] Add logic to calculate and update total_llm_cost on Invoice (OCR cost + sum of all line item KB costs)
- [ ] Update taxright serializers to include new cost fields in API responses
- [ ] Update taxright admin interface to display cost tracking fields