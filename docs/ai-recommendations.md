# AI-Assisted Maintenance Recommendations

## Purpose

The Smart Asset Lifecycle Tracker uses Amazon Bedrock to provide practical maintenance recommendations for authorized technicians and administrators.

AI recommendations are advisory. Maintenance dates are calculated deterministically by application code and remain authoritative.

## Amazon Bedrock Configuration

- Model: Amazon Nova Lite
- Model ID: `us.amazon.nova-lite-v1:0`
- API operation: Bedrock Runtime `Converse`
- Maximum output: 450 tokens
- Temperature: 0

A temperature of zero provides more consistent and repeatable structured responses.

## Information Sent to Bedrock

Only the following asset fields are included:

- Category
- Description
- Condition
- In-service date
- Useful-life months
- Status

Up to ten maintenance-history records may be included with:

- Maintenance type
- Description
- Performed date
- Condition after maintenance
- Next maintenance date

The deterministic maintenance schedule is included as the authoritative schedule.

Browser information, Cognito identities, email addresses, tokens, asset assignment details, and other unnecessary personal information are not sent to Bedrock.

## Prompt

```text
You are assisting an asset-maintenance technician.

Use only the supplied asset and maintenance information.
The authoritative cleaning and maintenance dates were calculated
by application code. Do not replace or modify those dates.

Return only a valid JSON object in this format:

{
  "recommendedActions": [
    "specific maintenance action"
  ],
  "riskLevel": "Low, Medium, High, or Critical",
  "rationale": "short explanation",
  "reviewStatus": "NeedsReview or NeedsManualEntry"
}

Rules:

- Provide between 1 and 5 practical actions.
- Do not invent serial numbers, users, costs, dates, or failures.
- Do not claim that an inspection was performed.
- Use NeedsManualEntry when the supplied data is insufficient.
- A technician must review the recommendation before applying it.
- Return JSON only without Markdown.
```

The application appends sanitized asset information, recent maintenance history, and the authoritative deterministic schedule to the prompt.

## Structured Output

Example validated response:

```json
{
  "recommendedActions": [
    "Continue routine cleaning and preventive maintenance as scheduled."
  ],
  "riskLevel": "Low",
  "rationale": "The asset is in good condition and its recent preventive maintenance was completed successfully.",
  "reviewStatus": "NeedsReview"
}
```

## Output Validation

The Lambda function validates the Bedrock response before returning it to the frontend.

Validation rules include:

- The response must be valid JSON.
- The top-level value must be an object.
- `recommendedActions` must contain between one and five strings.
- Each recommended action must be non-empty and no longer than 500 characters.
- `riskLevel` must be `Low`, `Medium`, `High`, or `Critical`.
- `rationale` must be a non-empty string no longer than 500 characters.
- `reviewStatus` must be `NeedsReview` or `NeedsManualEntry`.
- Markdown JSON fences are removed before validation.
- Invalid model output is rejected instead of being trusted.

## Human Review

AI output does not automatically modify an asset or create a maintenance record.

The authorized user must review the recommendation and decide whether maintenance work should be performed. If there is insufficient information, the model must return:

```json
{
  "reviewStatus": "NeedsManualEntry"
}
```

## Deterministic and Generative Responsibilities

| Application code | Amazon Bedrock |
|---|---|
| Calculates maintenance dates | Suggests practical actions |
| Calculates cleaning dates | Provides risk classification |
| Determines overdue status | Explains the recommendation |
| Preserves authoritative schedule | Identifies insufficient information |

This separation prevents the language model from replacing dates calculated by trusted application logic.

## Security Controls

- Bedrock invocation is restricted through the Lambda execution role.
- Only approved asset and maintenance fields are included.
- Identity and browser fields are excluded.
- Output is schema-validated before use.
- Temperature is set to zero.
- Recommendations require human review.
- AI output cannot directly update DynamoDB.
