# Depreciation Calculation

## Method

The Smart Asset Lifecycle Tracker calculates asset depreciation using the straight-line depreciation method.

The calculation is deterministic application logic. Amazon Bedrock does not calculate or replace financial values.

## Required Inputs

| Field | Description |
|---|---|
| `purchaseValue` | Original asset purchase value |
| `salvageValue` | Expected value after the useful life ends |
| `usefulLifeMonths` | Positive whole number of useful-life months |
| `inServiceDate` | Date the asset entered service, in `YYYY-MM-DD` format |
| `asOfDate` | Optional calculation date; defaults to the current date |

## Formulas

### Depreciable amount

```text
Depreciable amount = Purchase value − Salvage value
```

### Monthly depreciation

```text
Monthly depreciation = Depreciable amount ÷ Useful-life months
```

### Annual depreciation

```text
Annual depreciation = Monthly depreciation × 12
```

### Accumulated depreciation

```text
Accumulated depreciation =
Monthly depreciation × Depreciated months
```

Depreciated months cannot exceed the configured useful-life months.

### Current book value

```text
Current book value =
Purchase value − Accumulated depreciation
```

The book value never falls below the salvage value.

### Useful life consumed

```text
Useful-life consumed percentage =
Elapsed months × 100 ÷ Useful-life months
```

The percentage is capped at 100%.

### Estimated replacement date

```text
Estimated replacement date =
In-service date + Useful-life months
```

## Completed-Month Rule

Depreciation is based on completed monthly anniversaries, rather than partial months.

For an asset placed in service on January 31:

- February 27 represents zero completed months.
- February 28 represents one completed month.

End-of-month dates are adjusted to the final valid day of the destination month.

## Worked Example

Assume:

- Purchase value: `$1,400.00`
- Salvage value: `$200.00`
- Useful life: `24 months`
- In-service date: `2025-09-29`
- Calculation date: `2026-09-29`

Calculations:

```text
Depreciable amount = $1,400.00 − $200.00
                    = $1,200.00

Monthly depreciation = $1,200.00 ÷ 24
                     = $50.00

Annual depreciation = $50.00 × 12
                    = $600.00

Elapsed months = 12

Accumulated depreciation = $50.00 × 12
                         = $600.00

Current book value = $1,400.00 − $600.00
                   = $800.00

Useful life consumed = 12 × 100 ÷ 24
                     = 50.00%
```

The estimated replacement date is `2027-09-29`.

## Example Output

```json
{
  "asOfDate": "2026-09-29",
  "inServiceDate": "2025-09-29",
  "estimatedReplacementDate": "2027-09-29",
  "elapsedMonths": 12,
  "usefulLifeMonths": 24,
  "originalPurchaseValue": "1400.00",
  "salvageValue": "200.00",
  "annualDepreciation": "600.00",
  "accumulatedDepreciation": "600.00",
  "currentBookValue": "800.00",
  "usefulLifeConsumedPercent": "50.00"
}
```

## Rounding

Financial values are calculated using Python `Decimal` rather than binary floating-point arithmetic.

Returned currency values and percentages are rounded to two decimal places using `ROUND_HALF_UP`.

## Validation

The calculation rejects:

- Non-numeric or non-finite financial values
- Negative purchase values
- Negative salvage values
- Salvage values greater than the purchase value
- Zero, negative, fractional, or invalid useful-life values
- Dates not using ISO `YYYY-MM-DD` format

## Boundary Behavior

- An asset placed in service on the calculation date has no depreciation.
- A future in-service date produces zero elapsed months and zero depreciation.
- Depreciation stops after the useful life is fully consumed.
- Current book value never falls below salvage value.
- Useful-life consumption never exceeds 100%.
- End-of-month replacement dates use the last valid day of the applicable month.

## Automated Tests

The depreciation test suite covers:

- New assets with no depreciation
- Assets halfway through their useful life
- Assets older than their useful life
- Salvage-value validation
- Useful-life validation
- Future in-service dates
- Monthly-anniversary behavior
- End-of-month replacement dates

Run the tests with:

```text
python3 -m unittest backend/tests/test_depreciation.py -v
```
