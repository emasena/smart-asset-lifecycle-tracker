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

## Quick start with `scripts/dev.sh`

`scripts/dev.sh` wraps the manual steps below into single commands for a non-production test stack. It requires the AWS CLI configured for your account, the SAM CLI, `python3`, and `npm`.

```bash
scripts/dev.sh up                                                                 # test, build, deploy, write frontend/.env, seed sample data
scripts/dev.sh user -e you@example.com -g Administrator -d IT                     # create a confirmed login; password is prompted securely
scripts/dev.sh web                                                                # start the frontend
```

| Command                                              | What it does                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `up`                                                 | Runs unit tests, validates and builds (cached), deploys without prompts, writes `frontend/.env`, and seeds `sample-data/assets.json`                                                                                                                                               |
| `deploy`                                             | Build and deploy only, then refresh `frontend/.env`                                                                                                                                                                                                                                |
| `sync`                                               | Watches backend code and hot-syncs Lambda changes with `sam sync --watch` (dev stacks only)                                                                                                                                                                                        |
| `env`                                                | Writes `frontend/.env` from the stack outputs                                                                                                                                                                                                                                      |
| `seed`                                               | Loads the sample assets through the deployed Lambda, so validation and tag uniqueness still apply. Safe to re-run; existing tags are skipped                                                                                                                                       |
| `user -e EMAIL -g GROUP [-d DEPARTMENT] [-p PASSWORD]` | Creates a confirmed Cognito user in `GROUP`, optionally setting `custom:department`. The password must meet the pool policy (12+ characters with upper, lower, number, and symbol); you're prompted for it at a hidden prompt unless `-p` is given. Long forms: `--email`, `--password`, `--group`, `--department` |
| `web`                                                | Installs frontend dependencies if needed and runs the Vite dev server                                                                                                                                                                                                              |
| `smoke [--image PHOTO] [--keep]`                     | Smoke-tests the deployed stack by invoking each Lambda with synthetic Cognito claims, checks the logs for authorization errors, and writes `smoke-test-results.md`. Removes its test data unless `--keep` is given |
| `down [--purge]`                                     | Deletes the stack; `--purge` also deletes the retained DynamoDB table                                                                                                                                                                                                              |
| `test` / `build`                                     | Runs only the unit tests / only validate and build                                                                                                                                                                                                                                 |

Defaults can be overridden with environment variables: `ENVIRONMENT` (`dev` or `test`, default `dev`), `STACK_NAME` (default `smart-asset-tracker-$ENVIRONMENT`), and `AWS_REGION` (default `us-east-1`).

Wrap the password in single quotes so characters like `!` and `$` aren't interpreted by the shell. A password passed with `-p` is saved in your shell history; leave out `-p` to type it at a hidden prompt instead.

To test without touching the shared `dev` stack, use a different environment. Resource names are derived from `ENVIRONMENT`, so this creates a fully separate stack, table, functions, and user pool. Changing only `STACK_NAME` is not enough, because the table and function names would collide.

```bash
ENVIRONMENT=test scripts/dev.sh up
ENVIRONMENT=test scripts/dev.sh down --purge
```

## Test and deploy the backend manually

```bash
python3 -m unittest discover -s backend/tests -v
sam validate --template-file infrastructure/template.yaml
sam build --template-file infrastructure/template.yaml
sam deploy --guided
```

Use stack name `smart-asset-tracker-dev` and a development AWS region. After deployment, run `scripts/dev.sh env` (or copy the stack outputs into `frontend/.env` using `frontend/.env.example`).

### Tear down after testing

The stack has billable resources (DynamoDB, API Gateway, Cognito). Once you're done testing, delete it rather than leaving it running:

```bash
sam delete --stack-name smart-asset-tracker-dev
```

`AssetTable` and the photo S3 bucket have `DeletionPolicy: Retain`. The helper's
`down --purge` deletes the retained table after deleting the stack; the retained
photo bucket and its contents must be removed separately if no longer needed.

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

`scripts/dev.sh user -e EMAIL -g GROUP [-d DEPARTMENT]` does this in one step and prompts for the password.

For employee record scoping, set each asset's `assignedUserId` to the user's Cognito `sub`. For manager scoping, add a mutable Cognito custom attribute named `custom:department` and populate it before the user signs in.

## Security notes

- API permissions are enforced in Lambda as well as API Gateway.
- Employee and Manager access is restricted at record level.
- Technician updates are restricted to operational fields.
- Financial values are validated with `Decimal`, never floating point.
- Secrets and tokens must not be committed.
- The current scan-based search is appropriate only for the small Week 1 dataset; production access patterns should use indexes.

## Week 2: Secure Photo Intelligence

Week 2 expands the Smart Asset Lifecycle Tracker with secure asset-photo storage, Amazon Bedrock image analysis, and an authorized photo gallery.

### Features completed

- Private Amazon S3 bucket for asset photographs
- S3 Block Public Access and server-side encryption
- Five-minute presigned upload forms
- JPEG and PNG validation with a 3.75 MB limit
- Cognito role and department authorization
- User-specific upload paths under `pending/{user-id}/`
- S3-triggered asynchronous photo-analysis Lambda
- Amazon Bedrock Nova Lite multimodal analysis
- Structured and validated Bedrock JSON responses
- Suggested asset category, model, description, condition, useful life, estimated production date, maintenance category, and estimated value
- Manual approval before applying Bedrock suggestions
- Secure photo gallery with short-lived image-access URLs
- Backend authorization before every photo URL is generated
- DynamoDB transactions for unique asset tags
- CloudWatch logging and AWS X-Ray tracing
- Realistic equipment photographs replacing placeholder records

### Photo security

Asset photographs are never publicly accessible.

The backend generates a temporary image URL only after:

1. API Gateway validates the Cognito token.
2. Lambda reads the user identity and groups from verified Cognito claims.
3. Lambda loads the asset record from DynamoDB.
4. Lambda verifies the user’s role and access to that specific asset.
5. Amazon S3 generates a short-lived presigned URL.

Role, department, assignment, and ownership values supplied by the browser are not trusted.

### Role-based photograph access

- **Administrator:** access to all authorized asset photographs
- **Auditor:** read-only access according to the application policy
- **Manager:** photographs for assets in the manager’s department
- **Technician:** photographs within the technician’s authorized scope
- **Employee:** photographs for assets assigned to that employee
- **Unauthenticated or unauthorized user:** receives a `401` or `403` response

### Validation

```bash
python3 -m py_compile \
  backend/asset_api/app.py \
  backend/asset_api/domain.py \
  backend/asset_api/photo_analysis.py

python3 -m unittest discover -s backend/tests -v

sam validate --template-file infrastructure/template.yaml
sam build --template-file infrastructure/template.yaml

cd frontend
npm ci
npm run build
