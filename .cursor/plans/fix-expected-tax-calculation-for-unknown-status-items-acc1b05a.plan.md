<!-- acc1b05a-d3c3-490e-a74a-355f56ba84f5 0c85b8b0-a5e1-4dc1-a6a6-e4f7568ae100 -->
# Fix Expected Tax Calculation for Unknown Status Items

## Problem

The expected tax calculation in `verify_invoice_taxes()` only includes line items where `tax_status == 'taxable'` (line 815). This causes items with `tax_status = 'unknown'` to be skipped, even when KB verification correctly identifies they should be taxable with a non-zero `expected_tax_rate`.

In the reported case:

- Line item has `tax_status = 'unknown'` (from OCR)
- KB verification correctly returns `expected_tax_rate = 0.0675` (6.75%)
- But the item is skipped because `tax_status != 'taxable'`
- Result: `expected_tax = $0.00` instead of `$3325.00 * 0.0675 = $224.44`

## Solution

Update the expected tax calculation logic to include items that should be taxable based on KB verification results, not just items with `tax_status == 'taxable'`.

## Implementation

### Update `verify_invoice_taxes()` method (`taxright/services.py`, lines 813-845)

**Change the filtering logic** to include items in expected tax calculation if:

1. `tax_status == 'taxable'`, OR
2. KB verification returned a non-zero `expected_tax_rate` (indicating the item should be taxable)

**Specific changes:**

- Replace the check at line 815: `if line_item.tax_status != 'taxable':`
- New logic: Check if item should be included based on both `tax_status` and KB verification results
- If `tax_status == 'taxable'`: include it
- If `tax_status != 'taxable'` but `expected_rate_map.get(line_item.id)` exists and is > 0: include it (KB says it should be taxable)
- Only skip if `tax_status != 'taxable'` AND (no verification OR expected_rate is 0)

This ensures that items with `tax_status = 'unknown'` that the KB determines should be taxable are included in the expected tax calculation.

### To-dos

- [ ] Update the expected tax calculation filter in verify_invoice_taxes() to include items with 'unknown' tax_status when KB verification indicates they should be taxable (non-zero expected_tax_rate)