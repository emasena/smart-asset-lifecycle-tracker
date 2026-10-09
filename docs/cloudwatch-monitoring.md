# CloudWatch monitoring

Monitoring is defined in `infrastructure/template.yaml` and deploys with the rest of the stack — there is no separate manual step. It provisions:

- 30-day retention for the asset API and photo-analysis Lambda logs; 14-day retention for health, photo-upload, and photo-analysis-API logs
- Lambda error and throttle alarms for the asset API and photo-analysis functions
- A photo-upload error alarm
- An API Gateway 5XX alarm
- An SNS topic, with an optional email subscription

## Configure

Pass an email address as a stack parameter to receive alarm notifications:

```bash
sam deploy --parameter-overrides Environment=dev AlertEmail=your-email@example.com
```

Leaving `AlertEmail` blank (the default) skips creating the subscription — the topic and alarms are still created, so you can subscribe another endpoint (e.g. a queue) later.

Confirm the subscription using the link in the email AWS sends. Re-deploying with the same `AlertEmail` is a no-op for the subscription; changing it replaces the subscription.

### Migrating an existing deployment

Lambda auto-creates `/aws/lambda/<function>` on first invoke, so any environment that has run before already owns the log groups this template now declares. A plain deploy fails with "log group already exists". **Do not delete them** (that destroys the logs). Import them into the stack instead. Run this once per environment (`test`, `dev`, ...), before that environment's first deploy of this template. The groups are declared with `DeletionPolicy: Retain`, which import requires.

The six groups are `api`, `health`, `photo-upload`, `photo-analysis`, `photo-analysis-api` and `maintenance-scheduler`, with the template logical IDs `AssetApiLogGroup`, `HealthLogGroup`, `PhotoUploadLogGroup`, `PhotoAnalysisLogGroup`, `PhotoAnalysisApiLogGroup` and `MaintenanceSchedulerLogGroup`.

This procedure was verified end to end on a test stack (see the PR description).

1. **Find which groups already exist and record a baseline.** A function that never ran has no group; CloudFormation creates those in step 4, so only import the ones listed here. `storedBytes` lags by hours, so use the oldest log stream as the baseline instead:

   ```bash
   ENVIRONMENT=test   # match the stack you're migrating
   REGION=us-east-1
   for fn in api health photo-upload photo-analysis photo-analysis-api maintenance-scheduler; do
     echo -n "$fn  "
     aws logs describe-log-streams --region $REGION --order-by LogStreamName \
       --log-group-name "/aws/lambda/smart-asset-${fn}-${ENVIRONMENT}" \
       --query 'logStreams[0].[logStreamName,firstEventTimestamp]' --output text
   done
   ```

   A group that does not exist errors here; skip it. Save the output to compare after the migration.

2. **Build the import template from the *Processed* template.** Do not start from `infrastructure/template.yaml` or the deployed original: SAM re-expands those on every change set and generates new resource IDs (e.g. `AssetApiDeployment<hash>`), so the change set is rejected with `Resources [...] is missing from ResourceToImport list`. The Processed template is already expanded and matches the deployed resources exactly:

   ```bash
   aws cloudformation get-template --region $REGION --stack-name smart-asset-tracker-$ENVIRONMENT \
     --template-stage Processed --query TemplateBody --output json > processed.json
   ```

   Add one resource per existing group (from step 1) to `Resources` in `processed.json`, and write the log group names to `resources-to-import.json`. **Do not include `RetentionInDays` here.** An import only adopts the group and never changes it, so if the stack records the value now, the follow-up deploy sees no difference and never applies it (observed: retention stayed unset on all six groups):

   ```json
   "AssetApiLogGroup": {
     "Type": "AWS::Logs::LogGroup",
     "DeletionPolicy": "Retain",
     "UpdateReplacePolicy": "Retain",
     "Properties": { "LogGroupName": "/aws/lambda/smart-asset-api-test" }
   }
   ```

   ```json
   [{"ResourceType":"AWS::Logs::LogGroup","LogicalResourceId":"AssetApiLogGroup",
     "ResourceIdentifier":{"LogGroupName":"/aws/lambda/smart-asset-api-test"}}]
   ```

   Do not add alarms, the SNS topic or any other resource: an import change set may not create or modify anything else.

3. **Import.** Upload `processed.json` and pass it by URL (a SAM template can exceed the 51,200-byte inline limit), then review and execute the change set. It must contain only `Import` actions:

   ```bash
   aws s3 cp processed.json s3://<bucket>/import-template.json   # e.g. the SAM-managed source bucket
   aws cloudformation create-change-set --region $REGION \
     --stack-name smart-asset-tracker-$ENVIRONMENT --change-set-name import-log-groups \
     --change-set-type IMPORT --capabilities CAPABILITY_IAM \
     --template-url https://<bucket>.s3.$REGION.amazonaws.com/import-template.json \
     --parameters ParameterKey=Environment,UsePreviousValue=true ParameterKey=MaintenanceNotificationEmail,UsePreviousValue=true \
     --resources-to-import file://resources-to-import.json
   aws cloudformation wait change-set-create-complete --region $REGION --stack-name smart-asset-tracker-$ENVIRONMENT --change-set-name import-log-groups
   aws cloudformation describe-change-set --region $REGION --stack-name smart-asset-tracker-$ENVIRONMENT --change-set-name import-log-groups --query 'Changes[].ResourceChange.[Action,LogicalResourceId]'
   aws cloudformation execute-change-set --region $REGION --stack-name smart-asset-tracker-$ENVIRONMENT --change-set-name import-log-groups
   aws cloudformation wait stack-import-complete --region $REGION --stack-name smart-asset-tracker-$ENVIRONMENT
   ```

   If you also have stack parameters beyond `Environment` and `MaintenanceNotificationEmail`, add them with `UsePreviousValue=true`.

4. **Deploy the new template normally** (see `docs/photo-storage-migration.md` for the parameter ordering). This applies retention, creates the alarms and SNS topic, and creates any group that did not exist.

5. **Confirm nothing was lost.** Re-run the step 1 loop: each group's oldest stream and first-event timestamp must be unchanged, and `retentionInDays` should now be 30 (api, photo-analysis, maintenance-scheduler) or 14 (health, photo-upload, photo-analysis-api). `aws cloudformation list-stack-resources` should list all six `AWS::Logs::LogGroup` resources.

If you would rather not import, the alternative is to export each group to S3 (`aws logs create-export-task`) and then delete it before deploying; that keeps an archive but loses the live logs.

Any CloudWatch alarms or SNS topic/subscription created by the old script are unrelated to the ones this template manages and can be deleted separately once you've confirmed the new ones are in place.

## Inspect

List the alarms:

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix smart-asset \
  --region us-east-1 \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' \
  --output table
```

Tail application logs:

```bash
aws logs tail /aws/lambda/smart-asset-api-dev \
  --since 15m \
  --follow \
  --region us-east-1
```

Do not store AWS access keys or other credentials in this repository.
