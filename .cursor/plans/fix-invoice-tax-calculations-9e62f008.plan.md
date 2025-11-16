<!-- 9e62f008-4973-4ae2-8235-b661338aa04a 2f0c8c43-5a98-4400-a8be-a90eeba4b6d7 -->
# Fix Invoice Tax Calculation Issues

## Issues Identified

1. **`total_tax_amount` not extracted from OCR**: The `InvoiceDataParser.validate_and_extract()` method doesn't extract `total_tax_amount` from OCR JSON, so it's never saved to the Invoice model.

2. **`total_tax_amount` not saved when creating invoice**: The `create_invoice_from_ocr()` function doesn't set the `total_tax_amount` field even though it exists in the Invoice model.

3. **Actual Tax calculation is incorrect**: In `verify_invoice_taxes()`, `total_actual_tax` is calculated as the sum of line item tax amounts. When invoices show tax as a total (not per-line-item), all line items have `tax_amount: 0`, resulting in $0.00. Should use `invoice.total_tax_amount` if available.

4. **Expected Tax calculation may include exempt items**: The calculation should exclude exempt line items from expected tax.

## Implementation Plan

### 1. Update `InvoiceDataParser.validate_and_extract()` (`taxright/services.py`)

- Add `total_tax_amount` to the extracted data dictionary (line 64-72)
- Extract it using `_get_decimal('total_tax_amount', default=Decimal('0.00'))`

### 2. Update `create_invoice_from_ocr()` (`taxright/services.py`)

- Set `invoice.total_tax_amount = data['total_tax_amount']` when creating/updating invoice (lines 192-215)

### 3. Fix `verify_invoice_taxes()` actual tax calculation (`taxright/services.py`)

- Change line 725 to use `invoice.total_tax_amount` if it's > 0, otherwise fall back to summing line item tax amounts
- Logic: `total_actual_tax = invoice.total_tax_amount if invoice.total_tax_amount > 0 else sum(line_item.tax_amount for line_item in invoice.line_items.all())`

### 4. Fix `verify_invoice_taxes()` expected tax calculation (`taxright/services.py`)

- Update lines 721-724 to only include taxable items in expected tax calculation
- Filter out exempt items: only calculate expected tax for items where `line_item.tax_status == 'taxable'`

## Files to Modify

- `taxright/services.py`:
- `InvoiceDataParser.validate_and_extract()` method (around line 64-72)
- `create_invoice_from_ocr()` function (around lines 192-215)
- `BedrockKnowledgeBaseService.verify_invoice_taxes()` method (around lines 721-725)

### To-dos

- [ ] Add total_tax_amount extraction to InvoiceDataParser.validate_and_extract()
- [ ] Update create_invoice_from_ocr() to save total_tax_amount to Invoice model
- [ ] Fix actual tax calculation in verify_invoice_taxes() to use invoice.total_tax_amount
- [ ] Fix expected tax calculation to exclude exempt line items