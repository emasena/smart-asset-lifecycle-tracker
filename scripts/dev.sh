#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
case "$ENVIRONMENT" in
  dev|test) ;;
  *) echo "Only non-production ENVIRONMENT=dev or test is supported." >&2; exit 2 ;;
esac
STACK="smart-asset-tracker-$ENVIRONMENT"
FUNCTION="smart-asset-api-$ENVIRONMENT"

usage() {
  cat <<'EOF'
Usage: scripts/dev.sh COMMAND [options]
  up                     Test, build, deploy, configure frontend, seed assets
  sync                   Watch local Lambda changes with SAM sync
  seed                   Add sample-data/assets.json to the deployed stack
  user -e EMAIL -g GROUP [-p PASSWORD] [-d DEPARTMENT]
                         Create a confirmed user (prompts if -p is omitted)
  web                    Install frontend dependencies and run Vite
  env                    Write frontend/.env from CloudFormation outputs
  deploy                 Deploy the built SAM application without prompts
  test                   Run backend unit tests
  build                  Validate and build the SAM application
  down [--purge]         Delete the stack; --purge also deletes its retained table
  help                   Show this help

Environment: ENVIRONMENT=dev|test (default dev), AWS_REGION (default us-east-1).
Use a non-production AWS account/profile. The photo S3 bucket is retained on down.
EOF
}

need() { command -v "$1" >/dev/null || { echo "Missing required command: $1" >&2; exit 1; }; }
aws_cli() { aws --region "$AWS_REGION" --no-cli-pager "$@"; }
stack_output() {
  local value
  value="$(aws_cli cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text)"
  [[ -n "$value" && "$value" != None ]] || { echo "Missing stack output $1 in $STACK" >&2; exit 1; }
  printf '%s' "$value"
}
run_tests() { need python3; python3 -m unittest discover -s backend/tests -v; }
run_build() {
  need sam
  sam validate --template-file infrastructure/template.yaml
  if command -v python3.11 >/dev/null 2>&1; then
    sam build --template-file infrastructure/template.yaml --cached --parallel
  else
    need docker
    sam build --template-file infrastructure/template.yaml --cached --parallel --use-container
  fi
}
run_deploy() {
  need sam
  [[ -f .aws-sam/build/template.yaml ]] || { echo "Run scripts/dev.sh build first." >&2; exit 1; }
  sam deploy --template-file .aws-sam/build/template.yaml --stack-name "$STACK" \
    --region "$AWS_REGION" --resolve-s3 --s3-prefix "$STACK" \
    --capabilities CAPABILITY_IAM --parameter-overrides "Environment=$ENVIRONMENT" \
    --no-confirm-changeset --no-fail-on-empty-changeset
}
write_env() {
  need aws
  local api pool client
  api="$(stack_output ApiUrl)"
  pool="$(stack_output UserPoolId)"
  client="$(stack_output UserPoolClientId)"
  printf 'VITE_API_URL=%s\nVITE_AWS_REGION=%s\nVITE_USER_POOL_ID=%s\nVITE_USER_POOL_CLIENT_ID=%s\n' \
    "$api" "$AWS_REGION" "$pool" "$client" > frontend/.env
  echo "Wrote frontend/.env for $STACK"
}
run_seed() {
  need aws
  need python3
  local input output result status tag total=0 created=0 existing=0
  input="$(mktemp)"
  output="$(mktemp)"
  trap 'rm -f "$input" "$output"' RETURN
  while IFS= read -r asset; do
    tag="$(printf '%s' "$asset" | python3 -c 'import json,sys; print(json.load(sys.stdin)["assetTag"])')"
    python3 -c 'import json,sys; asset=json.load(sys.stdin); print(json.dumps({"httpMethod":"POST","resource":"/assets","requestContext":{"authorizer":{"claims":{"sub":"local-seed","cognito:groups":"[Administrator]"}}},"body":json.dumps(asset)}))' \
      <<< "$asset" > "$input"
    aws_cli lambda invoke --function-name "$FUNCTION" --cli-binary-format raw-in-base64-out \
      --payload "fileb://$input" "$output" >/dev/null
    status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["statusCode"])' "$output")"
    case "$status" in
      201) ((created+=1)); echo "Created $tag" ;;
      409) ((existing+=1)); echo "Already exists: $tag" ;;
      *) echo "Seed failed for $tag (HTTP $status): $(cat "$output")" >&2; return 1 ;;
    esac
    ((total+=1))
  done < <(python3 -c 'import json; [print(json.dumps(item)) for item in json.load(open("sample-data/assets.json"))]')
  echo "Seeded $total assets: $created created, $existing already present."
}
create_user() {
  need aws
  need python3
  local email='' password='' group='' department='' option pool
  OPTIND=1
  while getopts ':e:p:g:d:' option; do
    case "$option" in
      e) email="$OPTARG" ;; p) password="$OPTARG" ;;
      g) group="$OPTARG" ;; d) department="$OPTARG" ;;
      *) usage >&2; return 2 ;;
    esac
  done
  shift $((OPTIND-1))
  [[ $# -eq 0 && "$email" == *@*.* ]] || { usage >&2; return 2; }
  case "$group" in Employee|Technician|Manager|Administrator|Auditor) ;; *) echo "Invalid group." >&2; return 2 ;; esac
  if [[ -z "$password" ]]; then
    [[ -t 0 ]] || { echo "A terminal is needed to prompt for a password." >&2; return 2; }
    read -r -s -p 'Permanent password: ' password
    echo
  fi
  # Match the PasswordPolicy in infrastructure/template.yaml before any Cognito write.
  [[ ${#password} -ge 12 && "$password" =~ [[:lower:]] && "$password" =~ [[:upper:]] \
    && "$password" =~ [[:digit:]] && "$password" =~ [^[:alnum:]] ]] || {
    echo "Password must have at least 12 characters, uppercase, lowercase, number and symbol." >&2
    return 2
  }
  pool="$(stack_output UserPoolId)"
  local attributes=("Name=email,Value=$email" "Name=email_verified,Value=true")
  [[ -z "$department" ]] || attributes+=("Name=custom:department,Value=$department")
  aws_cli cognito-idp admin-create-user --user-pool-id "$pool" --username "$email" \
    --message-action SUPPRESS --temporary-password "$password" \
    --user-attributes "${attributes[@]}" >/dev/null
  aws_cli cognito-idp admin-set-user-password --user-pool-id "$pool" \
    --username "$email" --password "$password" --permanent
  aws_cli cognito-idp admin-add-user-to-group --user-pool-id "$pool" \
    --username "$email" --group-name "$group"
  echo "Created confirmed $group user $email in $STACK."
}

command="${1:-help}"
[[ $# -eq 0 ]] || shift
case "$command" in
  help|-h|--help) usage ;;
  test) run_tests ;;
  build) run_build ;;
  deploy) run_deploy ;;
  env) write_env ;;
  seed) run_seed ;;
  up) run_tests; run_build; run_deploy; write_env; run_seed ;;
  sync)
    need sam
    sam sync --watch --template-file infrastructure/template.yaml --stack-name "$STACK" \
      --region "$AWS_REGION" --parameter-overrides "Environment=$ENVIRONMENT"
    ;;
  user) create_user "$@" ;;
  web)
    need npm
    (cd frontend && npm ci && npm run dev)
    ;;
  down)
    [[ $# -eq 0 || ( $# -eq 1 && "$1" == '--purge' ) ]] || { usage >&2; exit 2; }
    need sam
    local_table=''
    if [[ ${1:-} == '--purge' ]]; then
      need aws
      local_table="$(stack_output AssetTableName)"
    fi
    sam delete --stack-name "$STACK" --region "$AWS_REGION" --no-prompts
    if [[ -n "$local_table" ]]; then
      aws_cli dynamodb delete-table --table-name "$local_table" >/dev/null
      echo "Deleted retained table $local_table."
    fi
    ;;
  *) usage >&2; exit 2 ;;
esac
