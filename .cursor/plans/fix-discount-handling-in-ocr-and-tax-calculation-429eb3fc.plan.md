<!-- 429eb3fc-e325-4404-999f-97a6e7af0f22 11ba493b-5422-4a63-b0bd-ff81f1f9dd7d -->
# Fix Discount Handling in OCR and Tax Calculation

## Problem

The OCR extraction is missing discount information, causing tax calculations to be performed on pre-discount line item amounts instead of the actual charged amounts. In the example:

- Line item shows: unit_price=3325, line_total=3325 (pre-discount)
- Invoice total_amount=1216.5 (post-discount)
- Tax is incorrectly calculated on $3325 instead of $1216.5

Discounts can be applied at two levels:

1. **Line-item discounts**: Applied to specific line items
2. **Invoice-level discounts**: Applied to the entire invoice (e.g., "Early payment discount", "Volume discount")

## Solution

### 1. Update OCR Prompt to Extract Discounts

**File**: `invoice_ocr/services.py`

- Update the default prompt template (lines 425-464) to explicitly request discount extraction
- Add `discount_amount` field to line items JSON schema
- Add `invoice_discount_amount` field to top-level invoice JSON schema
- Add instructions to distinguish between line-item and invoice-level discounts
- Add instructions to ensure `line_total` represents the post-discount amount (the actual amount charged)

### 2. Add Discount Fields to Models

**File**: `taxright/models.py`

- Add `discount_amount` field to `InvoiceLineItem` model (DecimalField, default=0.00)
- Add `invoice_discount_amount` field to `Invoice` model (DecimalField, default=0.00)
- This provides transparency and allows tracking of discounts separately at both levels

### 3. Update InvoiceDataParser to Handle Discounts

**File**: `taxright/services.py`

- Update `validate_and_extract()` to extract `invoice_discount_amount` from OCR JSON
- Update `_get_line_items()` method to extract `discount_amount` from each line item
- Add validation logic:
- For line items: if discount_amount is provided, ensure line_total = (quantity * unit_price) - discount_amount
- For invoice: validate that sum of line_totals - invoice_discount_amount ≈ total_amount (within tolerance)
- If discounts aren't explicitly extracted but totals don't match, infer discount from invoice total_amount vs sum of line_totals

### 4. Update Tax Calculation to Handle Invoice-Level Discounts

**File**: `taxright/services.py`

- Update `verify_invoice_taxes()` method to handle invoice-level discounts
- When calculating expected tax:
- For line-item discounts: use `line_total` which should already reflect the discount
- For invoice-level discounts: proportionally allocate the discount to taxable line items before calculating tax
- Allocation strategy: allocate invoice_discount_amount proportionally based on each line item's share of total taxable amount
- Formula: `discounted_line_total = line_total - (invoice_discount_amount * (line_total / sum_of_all_line_totals))`
- Calculate tax on the discounted amount: `expected_tax = discounted_line_total * expected_tax_rate`

### 5. Create Database Migrations

- Create Django migration for `discount_amount` field on `InvoiceLineItem`
- Create Django migration for `invoice_discount_amount` field on `Invoice`

## Implementation Details

### OCR Prompt Changes

- Add to line items JSON schema: `"discount_amount": "decimal number (discount applied to this specific line item, 0 if none)"`
- Add to top-level JSON schema: `"invoice_discount_amount": "decimal number (discount applied to entire invoice, 0 if none)"`
- Add instruction: "If a discount is applied to a specific line item, line_total should be the amount AFTER that discount"
- Add instruction: "If a discount is applied to the entire invoice (e.g., 'Early payment discount', 'Volume discount'), extract it as invoice_discount_amount"
- Add instruction: "If the invoice shows a total amount that is less than the sum of line_totals, determine if it's a line-item discount or invoice-level discount"

### Parser Validation

- After extracting line items, validate: `line_total = (quantity * unit_price) - discount_amount` for each line item
- Validate invoice: `sum(line_totals) - invoice_discount_amount ≈ total_amount` (within small tolerance for rounding)
- If validation fails, log warning and attempt to infer discount

### Tax Calculation Logic

- Calculate subtotal of all line items: `subtotal = sum(line_item.line_total for all items)`
- If `invoice.invoice_discount_amount > 0`:
- For each taxable line item, calculate proportional discount: `proportional_discount = invoice_discount_amount * (line_item.line_total / subtotal)`
- Calculate discounted amount: `discounted_amount = line_item.line_total - proportional_discount`
- Calculate tax on discounted amount: `expected_tax = discounted_amount * expected_tax_rate`
- If no invoice-level discount, use `line_item.line_total` directly (which should already reflect line-item discounts)

### To-dos

- [ ] Update OCR prompt in invoice_ocr/services.py to extract discount_amount and ensure line_total is post-discount
- [ ] Add discount_amount field to InvoiceLineItem model in taxright/models.py
- [ ] Update InvoiceDataParser._get_line_items() to extract and validate discount_amount
- [ ] Create Django migration for discount_amount field
- [ ] Add validation in tax calculation to warn if line_total appears pre-discount