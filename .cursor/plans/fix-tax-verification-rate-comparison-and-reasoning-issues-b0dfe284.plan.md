<!-- b0dfe284-ebc7-4c7b-a6db-e49b2a4f757c 7b1f385e-55ad-4b92-995b-c3247ec92824 -->
# Fix Tax Verification Rate Comparison and Reasoning Issues

## Problems Identified

1. **False Positive Rate Mismatch in Reasoning**: KB generates reasoning saying "6.75% does not match 6.7500%" when they're the same rate. The contradiction detection logic doesn't catch this precision-only difference pattern.

2. **Items Incorrectly Marked as Incorrect**: Some items with matching rates (0.0675 applied = 0.0675 expected) are marked incorrect because:

- KB returns `expected_tax_rate = 0.0000` for some items (e.g., "FM AOG 1-Hour Stainless Steel Gas Box Timer")
- When expected_rate = 0.0000 but applied_rate = 0.0675, the code correctly sets `is_correct = false`
- However, the fallback logic (lines 955-962) only affects expected tax calculation, not verification status

3. **Expected Tax Discrepancy**: Expected tax ($468.37) doesn't match actual ($438.75) because:

- Some items have incorrect `expected_tax_rate = 0.0000` from KB
- These items are either excluded from expected tax or use fallback applied rate inconsistently

4. **Reasoning Quality**: KB generates contradictory reasoning mentioning precision differences as if they're actual rate differences.

## Solution

### 1. Improve Contradiction Detection for Precision-Only Differences (`taxright/services.py`)

**Location**: `verify_line_item_tax()` method, contradiction detection section (lines 738-778)

- Add detection for reasoning text that mentions the same rate with different decimal precision (e.g., "6.75%" vs "6.7500%")
- When detected, if rates actually match within tolerance, override `is_correct = true` and update reasoning to note the correction
- Pattern: Look for percentage mentions in reasoning that, when normalized, match the applied/expected rates

### 2. Fix Verification Status When KB Returns Zero Expected Rate (`taxright/services.py`)

**Location**: `verify_line_item_tax()` method, rate validation section (lines 707-737)

- When KB returns `expected_tax_rate = 0.0000` but `applied_tax_rate > 0`:
- If the item is marked as `taxable` in OCR, this is likely a KB error
- Add logic to check if the reasoning suggests the item should be taxable (mentions tax rate > 0)
- If reasoning contradicts the 0.0000 expected rate, use applied_rate as the expected_rate for verification
- Only set `is_correct = false` if KB explicitly states the item should be exempt (expected_rate = 0.0000 with reasoning confirming exemption)

### 3. Improve Expected Tax Calculation Consistency (`taxright/services.py`)

**Location**: `verify_invoice_taxes()` method, expected tax calculation (lines 932-1000)

- When using fallback applied_rate for expected tax calculation (line 955-962), also update the verification result to reflect this
- Ensure that if an item uses fallback rate, it's included in expected tax calculation consistently
- Add logging to track when fallback rates are used vs when items are excluded

### 4. Enhance Prompt to Reduce KB Errors (`taxright/services.py`)

**Location**: `_build_tax_verification_prompt()` method (lines 433-527)

- Strengthen instructions to emphasize that if an item has an applied tax rate > 0 and is marked as taxable, the expected rate should typically match (unless explicitly exempt)
- Add example: "If invoice shows tax_rate = 0.0675 and tax_status = 'taxable', the expected_tax_rate should typically be 0.0675 unless this specific item type is exempt"
- Clarify that precision differences (6.75% vs 6.7500%) are not actual differences

### 5. Add Reasoning Text Normalization (`taxright/services.py`)

**Location**: `verify_line_item_tax()` method, after parsing response (line 705)

- Add function to normalize rate mentions in reasoning text (remove precision-only differences)
- Use normalized text for contradiction detection
- This helps catch cases where KB mentions "6.75%" and "6.7500%" as if they're different

## Files to Modify

1. **`taxright/services.py`**

- `verify_line_item_tax()`: Improve contradiction detection and rate validation
- `_build_tax_verification_prompt()`: Strengthen prompt instructions
- Add helper function for reasoning text normalization

## Implementation Details

- The contradiction detection should be more lenient for precision-only differences
- When KB returns 0.0000 for a taxable item, check reasoning before accepting it
- Ensure verification status and expected tax calculation use consistent logic
- Improve prompt to reduce KB errors in the first place

### To-dos

- [ ] Enhance contradiction detection to catch precision-only differences (6.75% vs 6.7500%) in reasoning text and correct false positives
- [ ] Fix verification status when KB returns expected_tax_rate=0.0000 for taxable items - check reasoning before accepting zero rate
- [ ] Ensure expected tax calculation uses consistent logic with verification status (when fallback rates are used)
- [ ] Strengthen prompt to reduce KB errors - emphasize that taxable items with applied rates should typically have matching expected rates
- [ ] Add helper function to normalize rate mentions in reasoning text for better contradiction detection