#!/usr/bin/env bash
# One-stop helper for deploying and testing the dev stack.
#
#   scripts/dev.sh up                 test, build, deploy, write frontend/.env, seed sample data
#   scripts/dev.sh deploy             build + deploy only (skips tests)
#   scripts/dev.sh sync               watch backend code and hot-sync Lambda changes (sam sync)
#   scripts/dev.sh env                write frontend/.env from the stack outputs
#   scripts/dev.sh seed               load sample-data/assets.json through the deployed Lambda
#   scripts/dev.sh user -e EMAIL -g GROUP [-d DEPARTMENT] [-p PASSWORD]
#                                     create a confirmed Cognito user in GROUP
#                                     (prompts for the password unless -p is given)
#   scripts/dev.sh web                start the Vite dev server
#   scripts/dev.sh smoke [--image F]  smoke-test the deployed stack; writes smoke-test-results.md
#   scripts/dev.sh down [--purge]     delete the stack (--purge also deletes the retained table)
#
# Override defaults with STACK_NAME, AWS_REGION, ENVIRONMENT (dev or test).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/infrastructure/template.yaml"
ENVIRONMENT="${ENVIRONMENT:-dev}"
STACK_NAME="${STACK_NAME:-smart-asset-tracker-$ENVIRONMENT}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
GROUPS_ALLOWED="Employee Technician Manager Administrator Auditor"

cd "$ROOT"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

reject_production_target() {
  case "$ENVIRONMENT" in
    dev|test) ;;
    *) die "Only non-production ENVIRONMENT=dev or test is supported." ;;
  esac
  local value normalized
  for value in "$ENVIRONMENT" "$STACK_NAME"; do
    normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
      prod|production|prod-*|production-*|*-prod|*-production|*-prod-*|*-production-*)
        die "Production target rejected: ENVIRONMENT=$ENVIRONMENT STACK_NAME=$STACK_NAME"
        ;;
    esac
  done
}

confirm_exact() {
  local prompt="$1" expected="$2" answer
  [[ -t 0 ]] || die "Confirmation requires an interactive terminal."
  printf '%s\n> ' "$prompt" >&2
  IFS= read -r answer
  [[ "$answer" == "$expected" ]] || die "Confirmation did not match. Nothing was deleted."
}

require() {
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null || die "'$cmd' is required but not installed."
  done
}

check_aws() {
  require aws sam
  aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || die "AWS credentials are not configured (run 'aws configure' or 'aws sso login')."
}

output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

# Like output, but fails when the stack or the output is missing.
stack_output() {
  local value
  value="$(output "$1")" || die "Could not read stack $STACK_NAME in $AWS_REGION."
  [[ -n "$value" && "$value" != "None" ]] || die "Stack $STACK_NAME has no output $1."
  printf '%s' "$value"
}

reject_production_target

cmd_test() {
  log "Running unit tests"
  python3 -m unittest discover -s backend/tests
}

cmd_build() {
  log "Validating template"
  sam validate --template-file "$TEMPLATE" --lint
  local build_args=(--template-file "$TEMPLATE" --cached --parallel)
  if ! command -v python3.11 >/dev/null; then
    log "python3.11 not found, building inside a container"
    build_args+=(--use-container)
  fi
  log "Building (cached)"
  sam build "${build_args[@]}"
}

cmd_deploy() {
  check_aws
  cmd_build
  log "Deploying $STACK_NAME to $AWS_REGION"
  sam deploy \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --resolve-s3 \
    --s3-prefix "$STACK_NAME" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "Environment=$ENVIRONMENT" \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset
  cmd_env
}

cmd_sync() {
  check_aws
  log "Watching for changes (Ctrl+C to stop). Dev stacks only — this skips changesets."
  sam sync \
    --template-file "$TEMPLATE" \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "Environment=$ENVIRONMENT" \
    --watch
}

cmd_env() {
  check_aws
  log "Writing frontend/.env from stack outputs"
  # Read every output first so a missing one never leaves a half-written file.
  local pool client api
  pool="$(stack_output UserPoolId)"
  client="$(stack_output UserPoolClientId)"
  api="$(stack_output ApiUrl)"
  cat > frontend/.env <<EOF
VITE_AWS_REGION=$AWS_REGION
VITE_USER_POOL_ID=$pool
VITE_USER_POOL_CLIENT_ID=$client
VITE_API_URL=$api
EOF
  cat frontend/.env
}

cmd_seed() {
  check_aws
  local fn="smart-asset-api-$ENVIRONMENT"
  log "Seeding sample assets through $fn"
  # Invoking the real handler with synthetic Administrator claims keeps
  # validation and the atomic tag reservation in play. Duplicates return 409;
  # any other response (including an unhandled Lambda error) fails the seed.
  FN="$fn" python3 - <<'PY'
import json, os, subprocess, sys, tempfile

with open("sample-data/assets.json") as f:
    assets = json.load(f)

created = existing = 0
for asset in assets:
    event = {
        "httpMethod": "POST",
        "body": json.dumps(asset),
        "requestContext": {"authorizer": {"claims": {
            "sub": "dev-seed-script", "cognito:groups": "Administrator"}}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as ev, \
         tempfile.NamedTemporaryFile(suffix=".json", delete=False) as out:
        json.dump(event, ev)
    try:
        subprocess.run(
            ["aws", "lambda", "invoke", "--function-name", os.environ["FN"],
             "--cli-binary-format", "raw-in-base64-out",
             "--payload", f"file://{ev.name}", out.name],
            check=True, stdout=subprocess.DEVNULL)
        with open(out.name) as f:
            result = json.load(f)
    finally:
        os.unlink(ev.name); os.unlink(out.name)
    status = result.get("statusCode") if isinstance(result, dict) else None
    if status == 201:
        created += 1
        print(f"  {asset['assetTag']}: created")
    elif status == 409:
        existing += 1
        print(f"  {asset['assetTag']}: already exists")
    else:
        sys.exit(f"Seed failed for {asset['assetTag']} (status {status}): {json.dumps(result)}")
print(f"  {len(assets)} assets: {created} created, {existing} already present")
PY
}

cmd_user() {
  check_aws
  local usage="Usage: dev.sh user -e EMAIL -g GROUP [-d DEPARTMENT] [-p PASSWORD]"
  local email="" password="" group="" department=""
  while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || die "Missing value for $1. $usage"
    case "$1" in
      -e|--email)      email="$2" ;;
      -p|--password)   password="$2" ;;
      -g|--group)      group="$2" ;;
      -d|--department) department="$2" ;;
      *) die "Unknown option '$1'. $usage" ;;
    esac
    shift 2
  done
  [[ -n "$email" && -n "$group" ]] || die "$usage"
  [[ " $GROUPS_ALLOWED " == *" $group "* ]] || die "GROUP must be one of: $GROUPS_ALLOWED"

  local pool
  pool="$(output UserPoolId 2>/dev/null || true)"
  [[ -n "$pool" && "$pool" != "None" ]] \
    || die "Stack $STACK_NAME not found in $AWS_REGION — run 'scripts/dev.sh deploy' first."

  if [[ -z "$password" ]]; then password="$(prompt_password)"; fi
  check_password "$password"

  local attrs=(Name=email,Value="$email" Name=email_verified,Value=true)
  [[ -n "$department" ]] && attrs+=(Name=custom:department,Value="$department")

  log "Creating $email in $group"
  if ! aws cognito-idp admin-get-user --user-pool-id "$pool" --username "$email" >/dev/null 2>&1; then
    aws cognito-idp admin-create-user --user-pool-id "$pool" --username "$email" \
      --user-attributes "${attrs[@]}" --message-action SUPPRESS >/dev/null
  elif [[ -n "$department" ]]; then
    aws cognito-idp admin-update-user-attributes --user-pool-id "$pool" --username "$email" \
      --user-attributes Name=custom:department,Value="$department"
  fi
  aws cognito-idp admin-set-user-password --user-pool-id "$pool" --username "$email" \
    --password "$password" --permanent
  aws cognito-idp admin-add-user-to-group --user-pool-id "$pool" --username "$email" \
    --group-name "$group"

  local sub
  sub="$(aws cognito-idp admin-get-user --user-pool-id "$pool" --username "$email" \
    --query "UserAttributes[?Name=='sub'].Value" --output text)"
  printf '  email: %s\n  group: %s\n  sub:   %s\n' "$email" "$group" "$sub"
}

# Prompts twice without echoing, for when the password should stay out of shell history.
prompt_password() {
  local password confirm
  [[ -t 0 ]] || die "No terminal to prompt on — pass the password with -p."
  read -rsp "Password: " password; echo >&2
  read -rsp "Confirm password: " confirm; echo >&2
  [[ "$password" == "$confirm" ]] || die "Passwords do not match."
  printf '%s' "$password"
}

# Mirrors the user pool's password policy so a bad password fails before calling Cognito.
check_password() {
  local password="$1"
  [[ ${#password} -ge 12 ]] || die "Password must be at least 12 characters."
  [[ "$password" =~ [[:lower:]] ]] || die "Password must contain a lowercase letter."
  [[ "$password" =~ [[:upper:]] ]] || die "Password must contain an uppercase letter."
  [[ "$password" =~ [[:digit:]] ]] || die "Password must contain a number."
  [[ "$password" =~ [^[:alnum:]] ]] || die "Password must contain a symbol."
  [[ "$password" != " "* && "$password" != *" " ]] || die "Password cannot start or end with a space."
}

cmd_web() {
  require npm
  [[ -f frontend/.env ]] || die "frontend/.env missing — run 'scripts/dev.sh env' first."
  cd frontend
  [[ -d node_modules ]] || npm ci
  npm run dev
}

cmd_down() {
  check_aws
  local account table purge=false
  case "${1:-}" in
    "") ;;
    --purge) purge=true ;;
    *) die "Usage: dev.sh down [--purge]" ;;
  esac

  account="$(aws sts get-caller-identity --query Account --output text)"
  table="$(output AssetTableName 2>/dev/null || true)"

  printf '\nDeletion target\n  AWS account: %s\n  Region:      %s\n  Stack:       %s\n' \
    "$account" "$AWS_REGION" "$STACK_NAME"
  confirm_exact "Type the stack name '$STACK_NAME' to confirm stack deletion:" "$STACK_NAME"

  if [[ "$purge" == true && -n "$table" && "$table" != "None" ]]; then
    printf '\nPurge target\n  DynamoDB table: %s\n' "$table"
    confirm_exact "Type the table name '$table' to confirm permanent table deletion:" "$table"
  fi

  log "Deleting stack $STACK_NAME"
  sam delete --stack-name "$STACK_NAME" --region "$AWS_REGION" --no-prompts
  if [[ "$purge" == true && -n "$table" && "$table" != "None" ]]; then
    log "Deleting retained table $table"
    aws dynamodb delete-table --table-name "$table" >/dev/null
  else
    log "Table ${table:-smart-asset-tracker-$ENVIRONMENT} was retained (use 'down --purge' to delete it)."
  fi
}

cmd_smoke() {
  require aws python3
  python3 scripts/smoke_test.py --env "$ENVIRONMENT" --stack "$STACK_NAME" --region "$AWS_REGION" "$@"
}

cmd_up() {
  cmd_test
  cmd_deploy
  cmd_seed
  log "Done. Create a login with: scripts/dev.sh user -e you@example.com -g Administrator -d IT (you'll be prompted for the password)"
  log "Then start the UI with:     scripts/dev.sh web"
}

case "${1:-up}" in
  up)     cmd_up ;;
  test)   cmd_test ;;
  build)  cmd_build ;;
  deploy) cmd_deploy ;;
  sync)   cmd_sync ;;
  env)    cmd_env ;;
  seed)   cmd_seed ;;
  user)   shift; cmd_user "$@" ;;
  web)    cmd_web ;;
  smoke)  shift; cmd_smoke "$@" ;;
  down)   shift; cmd_down "$@" ;;
  -h|--help|help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)      die "Unknown command '$1'. Run 'scripts/dev.sh help'." ;;
esac
