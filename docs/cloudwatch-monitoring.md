# CloudWatch monitoring

Monitoring is managed by two CloudFormation stacks:

- `infrastructure/template.yaml` manages the application, SNS topics, subscriptions, and application alarms.
- `infrastructure/monitoring-extension.yaml` manages the six Lambda log groups and the asset API throttling alarm.

This separation prevents existing log groups and alarms from blocking application deployments.

## Configure application alerts

Set `AlertEmail` when deploying the application stack to create an email subscription. Leaving it blank skips the subscription.

## Import existing monitoring resources

Do not delete existing Lambda log groups. Import them into `smart-asset-monitoring-<environment>` using `infrastructure/monitoring-extension.yaml` so their logs are preserved.

The monitoring stack owns:

- `AssetApiLogGroup`
- `HealthLogGroup`
- `PhotoUploadLogGroup`
- `PhotoAnalysisLogGroup`
- `PhotoAnalysisApiLogGroup`
- `MaintenanceSchedulerLogGroup`
- `AssetApiThrottlesAlarm`

Create a CloudFormation `IMPORT` change set using `LogGroupName` for each log group and `AlarmName` for the alarm. The change set must contain only `Import` actions. After executing it, deploy the main SAM template normally.

Run CloudFormation drift detection against both stacks and confirm that both report `IN_SYNC`.

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
