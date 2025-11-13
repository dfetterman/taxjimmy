#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   AWS_PROFILE=your-profile ./push.sh [dev] [--sync-perms|-p]
# 
# This script automatically reads defaults from zappa_settings.json:
#   - project_name -> PROJECT_NAME
#   - aws_region -> REGION
#   - ecr_repository_name -> REPO_NAME
#
# Optional environment overrides (override zappa_settings.json values):
#   REGION (default: from zappa_settings.json or us-east-1)
#   REPO_NAME (default: from zappa_settings.json or ${PROJECT_NAME}-lambda-container)
#   PROJECT_NAME (default: from zappa_settings.json or your_app_name)
#   RESYNC_IAM (default: 0)  # DEPRECATED: use --sync-perms instead

STAGE="${1:-dev}"
# Flags
RESYNC_IAM="${RESYNC_IAM:-0}"   # deprecated
SYNC_PERMS=0

# Parse optional flags
shift || true
for arg in "$@"; do
  case "$arg" in
    --resync-iam|-r)
      # backward compatibility: map to sync perms
      RESYNC_IAM=1
      SYNC_PERMS=1
      ;;
    --sync-perms|-p)
      SYNC_PERMS=1
      ;;
    *)
      # ignore unknown arguments for forward compatibility
      ;;
  esac
done
# Try to read defaults from zappa_settings.json if it exists
if [[ -f zappa_settings.json ]] && command -v jq >/dev/null 2>&1; then
  STAGE_FOR_CONFIG="${STAGE:-dev}"
  # Read project_name and aws_region from zappa_settings.json
  CONFIG_PROJECT_NAME=$(jq -r --arg stage "$STAGE_FOR_CONFIG" '.[$stage].project_name // empty' zappa_settings.json 2>/dev/null || echo "")
  CONFIG_REGION=$(jq -r --arg stage "$STAGE_FOR_CONFIG" '.[$stage].aws_region // empty' zappa_settings.json 2>/dev/null || echo "")
  CONFIG_ECR_REPO=$(jq -r --arg stage "$STAGE_FOR_CONFIG" '.[$stage].ecr_repository_name // empty' zappa_settings.json 2>/dev/null || echo "")
  
  # Use config values if available, otherwise fall back to defaults
  REGION="${REGION:-${CONFIG_REGION:-us-east-1}}"
  PROJECT_NAME="${PROJECT_NAME:-${CONFIG_PROJECT_NAME:-your_app_name}}"
  REPO_NAME="${REPO_NAME:-${CONFIG_ECR_REPO:-${PROJECT_NAME}-lambda-container}}"
else
  # Fall back to hardcoded defaults if zappa_settings.json doesn't exist
  REGION="${REGION:-us-east-1}"
  PROJECT_NAME="${PROJECT_NAME:-your_app_name}"
  REPO_NAME="${REPO_NAME:-${PROJECT_NAME}-lambda-container}"
fi

if [[ -z "${AWS_PROFILE:-}" ]]; then
  echo "Error: AWS_PROFILE must be set (e.g., export AWS_PROFILE=your-profile)" >&2
  exit 1
fi

echo "Stage...............: ${STAGE}"
echo "Region..............: ${REGION}"
echo "Repo name...........: ${REPO_NAME}"
echo "Project name........: ${PROJECT_NAME}"
echo "AWS Profile.........: ${AWS_PROFILE}"
echo "Sync extra perms....: ${SYNC_PERMS}"

ACCOUNT_ID=$(AWS_PROFILE="$AWS_PROFILE" aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"
LAMBDA_NAME="${PROJECT_NAME}-${STAGE}"

echo "Account ID..........: ${ACCOUNT_ID}"
echo "ECR URI.............: ${ECR_URI}"
echo "Lambda function.....: ${LAMBDA_NAME}"

echo "Assuming ECR repository already exists (managed by deploy.sh): ${REPO_NAME}"

echo "Logging in to ECR..."
AWS_PROFILE="$AWS_PROFILE" aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URI"

echo "Building Docker image (linux/amd64, disabling BuildKit to avoid OCI index)..."
export DOCKER_BUILDKIT=0
docker build \
  --platform linux/amd64 \
  --tag "$ECR_URI:latest" \
  .

echo "Pushing image to ECR..."
docker push "$ECR_URI:latest"

echo "Checking if Lambda function exists: ${LAMBDA_NAME}"
set +e
AWS_PROFILE="$AWS_PROFILE" aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" >/dev/null 2>&1
HAS_FN=$?
set -e

if [[ $HAS_FN -eq 0 ]]; then
  echo "Updating existing deployment via Zappa..."
  AWS_PROFILE="$AWS_PROFILE" zappa update "$STAGE" --docker-image-uri "$ECR_URI:latest"
else
  echo "Deploying new stage via Zappa..."
  AWS_PROFILE="$AWS_PROFILE" zappa deploy "$STAGE" --docker-image-uri "$ECR_URI:latest"
fi

# Optionally apply extra_permissions from zappa_settings.json as an inline policy on the execution role
if [[ "$SYNC_PERMS" == "1" ]]; then
  ROLE_NAME="${PROJECT_NAME}-${STAGE}-ZappaLambdaExecutionRole"
  POLICY_NAME="zappa-extra-permissions"
  echo "Applying extra_permissions from zappa_settings.json to role: ${ROLE_NAME}"

  if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required to sync permissions. Please install jq." >&2
    exit 1
  fi

  if [[ ! -f zappa_settings.json ]]; then
    echo "Error: zappa_settings.json not found in current directory." >&2
    exit 1
  fi

  STATEMENTS=$(jq -c --arg stage "$STAGE" '.[$stage].extra_permissions // []' zappa_settings.json)
  if [[ -z "$STATEMENTS" || "$STATEMENTS" == "null" || "$STATEMENTS" == "[]" ]]; then
    echo "No extra_permissions found for stage '$STAGE' in zappa_settings.json. Skipping."
  else
    TMP_POLICY_FILE=$(mktemp)
    printf '{\n  "Version": "2012-10-17",\n  "Statement": %s\n}\n' "$STATEMENTS" > "$TMP_POLICY_FILE"

    AWS_PROFILE="$AWS_PROFILE" aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "$POLICY_NAME" \
      --policy-document "file://${TMP_POLICY_FILE}"

    rm -f "$TMP_POLICY_FILE"
    echo "Extra permissions applied to role '${ROLE_NAME}'."
  fi
fi

echo "Done."
