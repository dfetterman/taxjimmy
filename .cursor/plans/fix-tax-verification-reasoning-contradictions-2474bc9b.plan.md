<!-- 2474bc9b-6a97-4f7a-99b0-75c8f015a198 d71b74e0-cf5b-445d-b3eb-1ccf56a15f25 -->
# Fix Tax Verification Reasoning Contradictions

## Problem

The tax verification system is generating contradictory reasoning where:

- Expected tax rate: 6.75% (0.0675)
- Applied tax rate: 0% (0.0000)
- But `is_correct` is set to `true` with reasoning saying the 0% rate is correct

The reasoning contradicts itself by stating the expected rate is 6.75% but then concluding the 0% applied rate is correct. Additionally, vendor information (like "Pete D'Anna" being a painter) is not included in the prompt, which could help the KB make better determinations.

## Solution

### 1. Add Vendor Information to Prompt (`taxright/services.py`)

- Modify `_build_tax_verification_prompt()` to include `vendor_name` from the invoice
- Add vendor context to help the KB understand the type of business/service
- This will help the KB make better tax determinations (e.g., painter services are typically taxable)

### 2. Strengthen Prompt Instructions (`taxright/services.py`)

- Add explicit instruction that if `expected_tax_rate` ≠ `applied_tax_rate`, then `is_correct` MUST be `false`
- Emphasize consistency: the reasoning must align with the `is_correct` boolean
- Add example of correct vs incorrect reasoning

### 3. Add Post-Processing Validation (`taxright/services.py`)

- In `verify_line_item_tax()`, after parsing the KB response, validate consistency:
- If `expected_tax_rate` ≠ `applied_tax_rate` (beyond tolerance), force `is_correct = false`
- Log a warning when this correction is made
- Optionally update the reasoning to note the correction

### 4. Improve Reasoning Validation

- Add a check that if the reasoning mentions the expected rate is different from applied rate, but `is_correct` is true, automatically correct it
- This catches cases where the KB generates contradictory text

## Files to Modify

1. **`taxright/services.py`**

- `_build_tax_verification_prompt()`: Add vendor_name and strengthen instructions
- `verify_line_item_tax()`: Add post-processing validation for consistency

## Implementation Details

The key changes:

- Include `invoice.vendor_name` in the prompt context
- Add explicit rule: "If expected_tax_rate ≠ applied_tax_rate, is_correct MUST be false"
- Add validation after parsing to enforce consistency
- Log corrections for monitoring

This ensures the system never reports a tax rate as correct when the expected and applied rates don't match, and provides better context to the KB through vendor information.

### To-dos

- [ ] Add vendor_name to _build_tax_verification_prompt() to provide business context to KB
- [ ] Add explicit instruction that expected_tax_rate ≠ applied_tax_rate means is_correct MUST be false
- [ ] Add post-processing validation in verify_line_item_tax() to enforce consistency between expected/applied rates and is_correct
- [ ] Add check for contradictory reasoning text and auto-correct when detected