# Monitoring and Logging

## Overview

The AWS Smart Asset Lifecycle Tracker uses Amazon CloudWatch for
operational monitoring, error detection, performance visibility, and
log retention.

## CloudWatch Dashboard

Dashboard name:

`smart-asset-lifecycle-dev`

The dashboard displays:

- Asset API Lambda invocations, errors, and throttles
- Asset API Lambda average duration
- API Gateway request count, 4XX errors, and 5XX errors
- Maintenance scheduler invocations and errors
- DynamoDB consumed capacity and throttle events

## CloudWatch Alarms

| Alarm | Metric | Purpose |
|---|---|---|
| smart-asset-api-errors-dev | Lambda Errors | Detect Asset API failures |
| smart-asset-scheduler-errors-dev | Lambda Errors | Detect scheduled maintenance failures |
| smart-asset-api-5xx-dev | API Gateway 5XXError | Detect server-side API failures |
| smart-asset-read-throttles-dev | DynamoDB ReadThrottleEvents | Detect throttled reads |
| smart-asset-write-throttles-dev | DynamoDB WriteThrottleEvents | Detect throttled writes |

Alarm notifications use the existing maintenance SNS topic.

## Log Retention

| Log group | Retention |
|---|---:|
| /aws/lambda/smart-asset-api-dev | 30 days |
| /aws/lambda/smart-asset-maintenance-scheduler-dev | 30 days |
| /aws/lambda/smart-asset-photo-analysis-api-dev | 30 days |
| /aws/lambda/smart-asset-photo-analysis-dev | 30 days |
| /aws/lambda/smart-asset-photo-upload-dev | 30 days |
| /aws/lambda/smart-asset-health-dev | 14 days |
| /aws/lambda/smart-asset-api-test | 14 days |

Retention limits CloudWatch storage costs and prevents indefinite log
storage. Existing log groups were configured with the AWS CLI because
they were created before the Week 4 monitoring resources.

## DynamoDB Operational Indexes

The following indexes were created through separate CloudFormation
updates because DynamoDB supports only one GSI creation or deletion per
table update:

- AssignedUserIndex — ACTIVE
- DepartmentIndex — ACTIVE

These indexes support scoped asset listing for employees, managers, and
technicians.

## Evidence

Submission screenshots should show:

1. CloudWatch dashboard
2. CloudWatch alarms in OK state
3. CloudWatch log-retention configuration
4. DynamoDB indexes in ACTIVE state

Screenshots must not contain credentials, tokens, passwords, or
presigned photograph URLs.
