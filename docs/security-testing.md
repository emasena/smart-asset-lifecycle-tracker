# Security Test Results

## Test Environment

- Environment: dev
- AWS Region: us-east-1
- API: Amazon API Gateway
- Authentication: Amazon Cognito
- Storage: Amazon DynamoDB and private Amazon S3
- Monitoring: Amazon CloudWatch

## Security Test Results

| Requirement | Expected result | Actual result | Status |
|---|---|---|---|
| Unauthenticated application access | Redirected to Cognito login | Login page displayed | Pass |
| API request without token | HTTP 401 | HTTP 401 | Pass |
| API request with invalid token | HTTP 401 | HTTP 401 | Pass |
| Auditor modifies an asset | HTTP 403 | HTTP 403 | Pass |
| Employee reads another user’s asset | HTTP 403 | HTTP 403 | Pass |
| Public photograph access | HTTP 403 | HTTP 403 | Pass |
| Authorized photograph access | HTTP 200 using a short-lived URL | HTTP 200; 300-second expiration | Pass |
| Malformed JSON input | HTTP 400 | HTTP 400 | Pass |
| Unsupported HTTP method | HTTP 405 | HTTP 405 | Pass |
| Credentials in source code | No credentials found | No credentials committed | Pass |

## Automated Test Result

The Week 4 security test suite validates authentication, authorization,
input handling, and unsupported HTTP methods.

Result: All security tests passed.

## Security Controls

- Amazon Cognito protects the application and API.
- API Gateway validates Cognito tokens.
- Role authorization is also enforced inside the Lambda application.
- Amazon S3 Block Public Access protects asset photographs.
- Authorized photograph access uses 300-second presigned URLs.
- Maintenance performer identity is taken from authenticated Cognito claims.
- Sensitive credentials and tokens are excluded from source control.

## Evidence

Screenshots are maintained separately and contain no passwords, tokens,
access keys, session credentials, or presigned URLs.
