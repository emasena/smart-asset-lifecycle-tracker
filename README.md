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

The non-production helper is the quickest way to deploy a complete local testing stack:

```bash
bash scripts/dev.sh up
ENVIRONMENT=test bash scripts/dev.sh up
```

`up` runs the backend tests, validates and builds SAM with `--cached --parallel`,
deploys without prompts, writes `frontend/.env` from that stack's outputs, and
loads the ten assets in `sample-data/assets.json`. When Python 3.11 is not
available locally, the build uses Docker with `--use-container`. Install and
configure the AWS CLI and SAM CLI first; Docker is needed for the container build.
The default region is `us-east-1`; set `AWS_REGION` to use another region.
`ENVIRONMENT=test` uses its own `smart-asset-tracker-test` stack, Cognito pool,
API, table, Lambda functions, and photo bucket. The helper accepts only `dev` and
`test`; use a non-production AWS account or profile.

| Command | Purpose |
| --- | --- |
| `bash scripts/dev.sh test` | Run the backend unit tests |
| `bash scripts/dev.sh build` | Validate and build the SAM template |
| `bash scripts/dev.sh deploy` | Deploy the built template without prompts |
| `bash scripts/dev.sh env` | Refresh `frontend/.env` from stack outputs |
| `bash scripts/dev.sh seed` | Add sample assets through the deployed asset Lambda |
| `bash scripts/dev.sh sync` | Run `sam sync --watch` for Lambda iteration |
| `bash scripts/dev.sh web` | Run `npm ci` and start the Vite dev server |
| `bash scripts/dev.sh down` | Delete the chosen stack |
| `bash scripts/dev.sh down --purge` | Delete the stack and its retained DynamoDB table |

`seed` invokes the deployed Lambda with synthetic Administrator claims. The
Lambda still validates every asset and reserves each tag atomically; a repeat
run treats HTTP 409 for existing tags as expected. These claims are for the
direct Lambda invocation only and do not grant browser users Administrator access.

For example, create a confirmed user in the selected stack:

```bash
bash scripts/dev.sh user -e ema@example.com -g Administrator
bash scripts/dev.sh user -e tech@example.com -g Technician -d IT
```

The command prompts for a password without echoing it. You may pass `-p PASSWORD`
for scripting, but the password can then appear in shell history and process
arguments. Passwords must meet the Cognito pool policy (12 characters, uppercase,
lowercase, number, and symbol). Groups are `Employee`, `Technician`, `Manager`,
`Administrator`, and `Auditor`. A department is needed for department-scoped
Technician and Manager access. Use `bash scripts/dev.sh help` for command help.

To run each SAM step manually:

```bash
python3 -m unittest discover -s backend/tests -v
sam validate --template-file infrastructure/template.yaml
sam build --template-file infrastructure/template.yaml
sam deploy --guided
```

Use stack name `smart-asset-tracker-dev` and a development AWS region. After
manual deployment, run `bash scripts/dev.sh env` to configure the frontend.

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
