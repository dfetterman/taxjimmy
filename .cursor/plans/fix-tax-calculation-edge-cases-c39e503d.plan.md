<!-- c39e503d-3018-427c-b0fb-5b4b97bd52a8 5b857c7c-b3d3-4901-9e56-f08ad7d6d404 -->
# Improve KB Tax Verification Prompt for Total Tax Invoices

## Problem Statement

When invoices show tax as a total (not per-line-item), line items have:

- `tax_amount = $0.00` (tax not shown per line)
- `tax_rate = 0.0675` (tax rate extracted from invoice)
- `invoice.total_tax_amount = $42.81` (total tax from invoice)

The current KB prompt shows "Applied Tax Amount: $0.00" which can be misleading and cause the KB to misinterpret the situation, potentially:

1. Thinking no tax was applied when tax_rate > 0
2. Confusing exempt items (tax_rate = 0) with total-tax invoices (tax_amount = 0, tax_rate > 0)
3. Returning incorrect expected_tax_rate values

## Implementation Plan

### 1. Enhance `_build_tax_verification_prompt()` Method

**Location:** `taxright/services.py`, lines 385-443

**Changes:**

- Add context about invoice-level tax information
- Clarify when `tax_amount = $0.00` but `tax_rate > 0` (tax shown as total)
- Include `invoice.total_tax_amount` in prompt if available and relevant
- Add explicit note distinguishing total-tax vs per-line-tax invoices
- Improve prompt structure to make tax application method clear

**Specific Updates:**

1. Accept `invoice` parameter (or at minimum `total_tax_amount`) in `_build_tax_verification_prompt()`
2. Detect tax display pattern:

- If `tax_amount = 0` AND `tax_rate > 0` AND `invoice.total_tax_amount > 0`: Tax shown as total
- If `tax_amount > 0`: Tax shown per-line-item
- If `tax_amount = 0` AND `tax_rate = 0`: Potentially exempt

3. Add contextual note to prompt explaining the tax display method
4. Include invoice total_tax_amount in prompt when relevant
5. Update prompt to guide KB to focus on tax_rate for verification

### 2. Update `verify_line_item_tax()` Method

**Location:** `taxright/services.py`, lines 571-680

**Changes:**

- Pass `invoice` object (or `total_tax_amount`) to `_build_tax_verification_prompt()`
- Ensure invoice context is available for prompt building

### 3. Update Method Signature

**Location:** `taxright/services.py`

**Changes:**

- Update `_build_tax_verification_prompt()` signature to accept invoice or total_tax_amount
- Update all callers of this method

## Files to Modify

- `taxright/services.py`:
- `_build_tax_verification_prompt()` method (lines 385-443)
- `verify_line_item_tax()` method (lines 571-680) - to pass invoice context
- Update method signature and all call sites

## Expected Improvements

1. **Clearer Context**: KB will understand when tax is shown as total vs per-line
2. **Better Verification**: KB won't misinterpret $0.00 tax_amount when tax_rate is applied
3. **Accurate Responses**: KB will return correct expected_tax_rate values
4. **Reduced False Negatives**: Fewer cases where KB incorrectly flags correct tax applications

## Testing Considerations

- Test with invoices where tax is shown as total (tax_amount=0, tax_rate>0, total_tax_amount>0)
- Test with invoices where tax is shown per-line-item (tax_amount>0 for each line)
- Test with exempt items (tax_amount=0, tax_rate=0)
- Verify KB responses are more accurate with improved context

### To-dos

- [ ] Update _build_tax_verification_prompt() to accept invoice parameter for context
- [ ] Add logic to detect tax display pattern (total vs per-line vs exempt)
- [ ] Enhance prompt text to clarify tax display method and include invoice total_tax_amount context
- [ ] Update verify_line_item_tax() to pass invoice context to prompt builder