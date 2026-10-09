# Final Demonstration Script

## 1. Unauthenticated Access

1. Open the application in a private browser window.
2. Show that the asset inventory is not visible.
3. Confirm that the Cognito login page is displayed.

Expected result: unauthenticated users cannot access application data.

## 2. Successful Cognito Login

1. Sign in with an authorized Cognito test user.
2. Complete MFA if requested.
3. Show the authenticated application and authorized inventory.

Expected result: the user receives access appropriate to their Cognito group.

## 3. Manual Asset Creation

Create an asset manually with valid values:

- Asset tag
- Category
- Description
- Purchase date
- In-service date
- Purchase value
- Salvage value
- Useful life
- Department
- Condition
- Status

Expected result: the asset is saved to DynamoDB and appears in the authorized inventory.

## 4. Photograph-Assisted Asset Creation

1. Select a valid JPEG or PNG photograph.
2. Upload the photograph.
3. Explain that it is stored privately in Amazon S3.
4. Wait for Amazon Bedrock analysis.
5. Display the suggested category, description, condition, useful life, and maintenance category.

Expected result: AI-generated suggestions are displayed for review.

## 5. Review and Correction of AI Information

1. Apply the AI suggestions.
2. Modify at least one suggestion manually.
3. Explain that AI output is advisory and does not bypass user review.
4. Create the asset only after reviewing the fields.

Expected result: reviewed and corrected information is stored.

## 6. Manual Fallback

1. Upload an image that cannot be identified confidently, or demonstrate a `NeedsManualEntry` result.
2. Reject or leave the AI suggestions unapplied.
3. Enter the asset information manually.
4. Create the asset.

Expected result: the application remains usable when AI analysis is unavailable or insufficient.

## 7. Depreciation Calculation

1. Open an asset with purchase value, salvage value, useful life, and in-service date.
2. Show:
   - Original purchase value
   - Annual depreciation
   - Accumulated depreciation
   - Current book value
   - Useful-life percentage consumed
   - Estimated replacement date
3. Explain that application code performs the calculation, not Bedrock.

Expected result: deterministic straight-line depreciation is displayed.

## 8. Maintenance Record

1. Open the asset’s maintenance page.
2. Enter:
   - Maintenance type
   - Description
   - Performed date
   - Cost
   - Condition after service
   - Optional next maintenance date
3. Save the maintenance record.
4. Show it in the maintenance-history table.
5. Explain that `performedBy` comes from the authenticated Cognito identity.

Expected result: the record is stored using the asset maintenance key pattern.

## 9. AI-Assisted Recommendation

1. Select Generate Recommendation.
2. Show:
   - Recommended actions
   - Risk level
   - Rationale
   - Review status
3. Explain that deterministic schedule dates are authoritative.
4. Explain that Bedrock output is validated before display.

Expected result: a structured recommendation requiring human review is displayed.

## 10. Restricted Action

1. Sign out from the Administrator or Technician account.
2. Sign in as an Auditor.
3. Attempt to modify an asset or create a maintenance record.

Expected result: the operation is blocked with `403 Forbidden` or the unauthorized action is unavailable in the interface.

## 11. CloudWatch Monitoring

Show the `smart-asset-lifecycle-dev` dashboard, including:

- Lambda invocations
- Lambda errors
- Lambda throttles
- Lambda duration
- API Gateway request count
- API Gateway 4XX and 5XX responses
- Maintenance scheduler invocations and errors
- DynamoDB consumption and throttle events

Also show:

- CloudWatch alarms in `OK` state
- Lambda log events
- Configured log-retention periods

Expected result: application activity and operational health are observable.

## 12. Logout

1. Return to the application.
2. Select Sign out.
3. Attempt to access the application again.

Expected result: the Cognito login page is displayed and asset data is no longer accessible.

## Closing Summary

The demonstration proves that the application provides:

- Cognito authentication
- Role-based authorization
- Protected API endpoints
- Manual and AI-assisted asset creation
- Private photograph storage
- Deterministic depreciation
- Maintenance-history tracking
- AI-assisted recommendations
- CloudWatch monitoring
- Secure logout and session termination

## Suggested Timing

| Demonstration section | Target time |
|---|---:|
| Introduction and architecture | 2 minutes |
| Login and manual asset creation | 2 minutes |
| Photograph and AI workflow | 3 minutes |
| Depreciation and maintenance | 3 minutes |
| Restricted action and security | 2 minutes |
| CloudWatch monitoring | 2 minutes |
| Logout and conclusion | 1 minute |
| **Total** | **15 minutes** |
