# AWS Smart Asset Lifecycle Tracker

A secure serverless asset-management application built with Amazon Cognito, API Gateway, Lambda, DynamoDB, S3, Amazon Bedrock, EventBridge, SNS, and CloudWatch. SailPoint is planned as the identity-governance and lifecycle-provisioning layer while Cognito remains the application's authentication and JWT provider.

## Current milestone

The starter implements the Week 1 foundation:

- AWS SAM infrastructure
- Cognito user pool and five application groups
- API Gateway Cognito authorizer
- DynamoDB asset table
- Python Lambda REST API for create, list, view, and update
- Backend RBAC and record-scope authorization
- React login and manual asset-entry interface
- Ten sample assets and unit tests
- SailPoint-to-Cognito role mapping documentation

## Architecture

See [`docs/architecture.md`](docs/architecture.md), [`docs/data-model.md`](docs/data-model.md), [`docs/role-permissions.md`](docs/role-permissions.md), and [`docs/sailpoint-integration.md`](docs/sailpoint-integration.md).

## Architecture diagrams

See [`docs/architecture/README.md`](docs/architecture/README.md) for the complete four-week target architecture and the weekly architecture progression diagrams.

## Prerequisites

- AWS CLI configured for a non-production AWS account
- AWS SAM CLI
- Python 3.11 (matches the Lambda `Runtime` in `infrastructure/template.yaml`; required for a native `sam build` — use `sam build --use-container` instead if you don't have 3.11 installed locally)
- Node.js 20 or later

## Test and deploy the backend

```bash
python3 -m unittest discover -s backend/tests -v
sam validate --template-file infrastructure/template.yaml
sam build --template-file infrastructure/template.yaml
sam deploy --guided
```

Use stack name `smart-asset-tracker-dev` and a development AWS region. After deployment, copy the stack outputs into `frontend/.env` using `frontend/.env.example`.

### Tear down after testing

The stack has billable resources (DynamoDB, API Gateway, Cognito). Once you're done testing, delete it rather than leaving it running:

```bash
sam delete --stack-name smart-asset-tracker-dev
```

`AssetTable` has `DeletionPolicy: Retain`, so the DynamoDB table survives the stack delete — remove it manually from the AWS Console/CLI if you don't need the data anymore.

## Run the frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Create test users

Create users in Cognito, confirm them, and assign them to one of these groups:

- `Employee`
- `Technician`
- `Manager`
- `Administrator`
- `Auditor`

For employee record scoping, set each asset's `assignedUserId` to the user's Cognito `sub`. For manager scoping, add a mutable Cognito custom attribute named `custom:department` and populate it before the user signs in.

## Security notes

- API permissions are enforced in Lambda as well as API Gateway.
- Employee and Manager access is restricted at record level.
- Technician updates are restricted to operational fields.
- Financial values are validated with `Decimal`, never floating point.
- Secrets and tokens must not be committed.
- The current scan-based search is appropriate only for the small Week 1 dataset; production access patterns should use indexes.

## Next milestone

Week 2 adds a private S3 bucket, presigned uploads, Bedrock image analysis with structured output, manual fallback, and mandatory human confirmation before saving AI suggestions.
