#!/bin/bash

# Exit on any error
set -e

# Function to prompt for yes/no confirmation
confirm() {
    read -r -p "${1:-Are you sure?} [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) 
            true
            ;;
        *)
            false
            ;;
    esac
}

# Source the VPC selection functions
source deploy/select-vpc.sh

# Add app name parameter handling at the start
if [ -z "$1" ]; then
    echo "Error: Application name parameter is required"
    echo "Usage: $0 <app_name>"
    echo "Example: $0 your_app_name"
    exit 1
fi

APP_NAME="$1"

# Get AWS account ID if not already set
if [ -z "${AWS_ACCOUNT_ID:-}" ]; then
    echo "Getting AWS account ID..."
    if [ -z "${AWS_PROFILE:-}" ]; then
        AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    else
        AWS_ACCOUNT_ID=$(AWS_PROFILE="$AWS_PROFILE" aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    fi
    
    if [ -z "$AWS_ACCOUNT_ID" ]; then
        echo "Error: Could not determine AWS account ID. Please set AWS_PROFILE or configure AWS CLI."
        exit 1
    fi
    echo "AWS Account ID: $AWS_ACCOUNT_ID"
else
    echo "Using provided AWS Account ID: $AWS_ACCOUNT_ID"
fi

# # Check if app_name directory exists and rename it if needed
# if [ -d "app_name" ] && [ ! -d "$APP_NAME" ]; then
#     echo "Renaming 'app_name' directory to '$APP_NAME'..."
#     mv app_name "$APP_NAME"
#     echo "Directory renamed successfully."
# elif [ -d "app_name" ] && [ -d "$APP_NAME" ]; then
#     echo "Warning: Both 'app_name' and '$APP_NAME' directories exist."
#     if confirm "Do you want to remove the 'app_name' directory?"; then
#         rm -rf app_name
#         echo "Removed 'app_name' directory."
#     fi
# fi

# SETTINGS_FILE="${APP_NAME}/settings.py"

# # Verify settings file exists
# if [ ! -f "$SETTINGS_FILE" ]; then
#     echo "Error: Settings file not found: $SETTINGS_FILE"
#     echo "Please ensure your Django project is set up with the correct project name."
#     exit 1
# fi

# Function to replace placeholders in a file
replace_placeholders() {
    local file="$1"
    local app_name="$2"
    local account_id="$3"
    
    if [ ! -f "$file" ]; then
        return 0  # File doesn't exist, skip silently
    fi
    
    # Create backup
    cp "$file" "${file}.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    
    # Replace your_app_name with actual app name
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS uses BSD sed
        sed -i '' "s/your_app_name/$app_name/g" "$file"
        sed -i '' "s/ACCOUNT_ID/$account_id/g" "$file"
    else
        # Linux uses GNU sed
        sed -i "s/your_app_name/$app_name/g" "$file"
        sed -i "s/ACCOUNT_ID/$account_id/g" "$file"
    fi
}

# Update placeholders in key files
echo "Updating placeholders in configuration files..."
# COMMENTED OUT: Changes to app_name/ directory files
# replace_placeholders "$SETTINGS_FILE" "$APP_NAME" "$AWS_ACCOUNT_ID"
# replace_placeholders "${APP_NAME}/urls.py" "$APP_NAME" "$AWS_ACCOUNT_ID"
# replace_placeholders "${APP_NAME}/asgi.py" "$APP_NAME" "$AWS_ACCOUNT_ID"
# replace_placeholders "${APP_NAME}/wsgi.py" "$APP_NAME" "$AWS_ACCOUNT_ID"
replace_placeholders "zappa_settings.json" "$APP_NAME" "$AWS_ACCOUNT_ID"
replace_placeholders "manage.py" "$APP_NAME" "$AWS_ACCOUNT_ID"
echo "Placeholders updated."

echo "Deploying application: $APP_NAME"
echo "You should run this script from the root of your project repo."
echo "You should have the AWS CLI installed and configured."
echo "You should have SAM CLI installed."
echo ""
echo "Usage example:"
echo "  AWS_PROFILE=your-profile ./deploy.sh your_app_name"

# RDS Deployment
if confirm "Do you want to deploy RDS resources?"; then
    echo "Starting RDS deployment..."
    
    # Get VPC ID and CIDR
    vpc_info=$(select_vpc) || { echo "Failed to get valid VPC ID. Exiting."; exit 1; }
    read -r vpc_id vpc_cidr <<< "$vpc_info"  # Use read to split on whitespace
    
    echo "Debug: Selected VPC ID is: $vpc_id" >&2
    echo "Debug: Selected VPC CIDR is: $vpc_cidr" >&2
    
    if [[ ! $vpc_cidr =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
        echo "Error: Invalid CIDR format: $vpc_cidr" >&2
        exit 1
    fi
    
    # Get subnet data and selections
    subnet_ids=$(select_subnets "$vpc_id") || { echo "Failed to get subnet data. Exiting."; exit 1; }
    
    # Split the returned subnet IDs into two variables
    read -r subnet1 subnet2 <<< "$subnet_ids"
    
    if [ -z "$subnet1" ] || [ -z "$subnet2" ]; then
        echo "Could not get two valid subnet IDs. Exiting."
        exit 1
    fi
    
    echo "Using subnets: $subnet1 and $subnet2"
    
    # Generate a password that meets RDS requirements:
    # - At least 8 characters
    # - Contains uppercase letters, lowercase letters, numbers
    # - Only printable ASCII characters (no /, @, ", or spaces)
    db_password=$(cat /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9!#$%&*+,-.=?^_`{|}~' | head -c 32)
    
    # Ensure password has at least one of each required character type
    db_password="${db_password}A1a!"

    # Format parameters for SAM
    parameters="AppName=$APP_NAME"
    parameters="$parameters VpcId=$vpc_id"
    parameters="$parameters VpcCidr=$vpc_cidr"
    parameters="$parameters SubnetIds=$subnet1,$subnet2"
    parameters="$parameters DBUsername=${APP_NAME}_admin"
    parameters="$parameters DBName=${APP_NAME}db"
    parameters="$parameters DBPassword=$db_password"

    # Deploy RDS stack with updated name
    echo "Deploying RDS resources..."
    if ! sam deploy \
        --template-file deploy/template-rds.yaml \
        --stack-name ${APP_NAME}-rds \
        --region us-east-1 \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides "$parameters" \
        --no-confirm-changeset; then
        echo "Note: If you see 'No changes to deploy', this is expected if the stack is up to date."
    fi

    # Get RDS cluster details from CloudFormation outputs
    echo "Getting RDS cluster details..."
    cluster_endpoint=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-rds \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`ClusterEndpoint`].OutputValue' \
        --output text)
    
    cluster_port=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-rds \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`ClusterPort`].OutputValue' \
        --output text)
    
    db_name=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-rds \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`DBName`].OutputValue' \
        --output text)
    
    # Get the actual cluster identifier from CloudFormation outputs (preferred method)
    cluster_identifier=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-rds \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`ClusterIdentifier`].OutputValue' \
        --output text 2>/dev/null || echo "")
    
    # Fallback 1: Get from CloudFormation stack resources
    if [ -z "$cluster_identifier" ] || [ "$cluster_identifier" = "None" ]; then
        cluster_identifier=$(aws cloudformation describe-stack-resources \
            --stack-name ${APP_NAME}-rds \
            --region us-east-1 \
            --logical-resource-id AuroraCluster \
            --query 'StackResources[0].PhysicalResourceId' \
            --output text 2>/dev/null || echo "")
    fi
    
    # Fallback 2: Query RDS by endpoint
    if [ -z "$cluster_identifier" ] || [ "$cluster_identifier" = "None" ]; then
        echo "Getting cluster identifier from RDS by endpoint..."
        # Query all clusters and match by endpoint address
        cluster_identifier=$(aws rds describe-db-clusters \
            --region us-east-1 \
            --query "DBClusters[?Endpoint.Address=='${cluster_endpoint}'].DBClusterIdentifier" \
            --output text 2>/dev/null || echo "")
    fi
    
    # Fallback 3: Extract from endpoint hostname
    # Format: cluster-id.cluster-xyz.region.rds.amazonaws.com
    if [ -z "$cluster_identifier" ] || [ "$cluster_identifier" = "None" ]; then
        # Extract the part before the first dot
        cluster_identifier=$(echo "$cluster_endpoint" | cut -d'.' -f1)
        echo "Extracted cluster identifier from endpoint: $cluster_identifier"
    fi
    
    if [ -n "$cluster_identifier" ] && [ "$cluster_identifier" != "None" ]; then
        echo "Using cluster identifier: $cluster_identifier"
    fi

    # Update secrets manager with complete database details
    if confirm "Do you want to save database credentials to Secrets Manager?"; then
        echo "Saving database credentials to AWS Secrets Manager..."
        secret_name="${APP_NAME}/rds/credentials"
        secret_string="{
            \"username\":\"${APP_NAME}_admin\",
            \"password\":\"$db_password\",
            \"engine\":\"postgres\",
            \"host\":\"$cluster_endpoint\",
            \"port\":$cluster_port,
            \"dbname\":\"$db_name\",
            \"dbClusterIdentifier\":\"${cluster_identifier:-${APP_NAME}-cluster}\"
        }"
        
        # Check if secret already exists
        if aws secretsmanager describe-secret --name "$secret_name" --region us-east-1 >/dev/null 2>&1; then
            echo "Secret already exists. Updating..."
            aws secretsmanager update-secret \
                --name "$secret_name" \
                --secret-string "$secret_string" \
                --region us-east-1 >/dev/null
        else
            aws secretsmanager create-secret \
                --name "$secret_name" \
                --description "${APP_NAME} RDS credentials" \
                --secret-string "$secret_string" \
                --region us-east-1 >/dev/null
        fi
        echo "Database credentials saved to Secrets Manager: $secret_name"
    fi

    # Wait for RDS cluster to be available
    if [ -z "$cluster_identifier" ] || [ "$cluster_identifier" = "None" ]; then
        echo "Warning: Could not determine cluster identifier. Skipping availability check."
        echo "Cluster endpoint: $cluster_endpoint"
        cluster_status="unknown"
    else
        echo "Waiting for RDS cluster to be available (this may take several minutes)..."
        echo "Cluster identifier: $cluster_identifier"
        max_attempts=60
        attempt=0
        
        while [ $attempt -lt $max_attempts ]; do
            cluster_status=$(aws rds describe-db-clusters \
                --db-cluster-identifier "$cluster_identifier" \
                --region us-east-1 \
                --query 'DBClusters[0].Status' \
                --output text 2>/dev/null || echo "not-found")
            
            if [ "$cluster_status" = "available" ]; then
                echo "RDS cluster is now available!"
                break
            elif [ "$cluster_status" = "not-found" ]; then
                echo "Warning: Could not find cluster with identifier '$cluster_identifier'. It may still be creating..."
            else
                echo "Cluster status: $cluster_status (attempt $((attempt + 1))/$max_attempts)"
            fi
            
            if [ $attempt -lt $((max_attempts - 1)) ]; then
                sleep 10
            fi
            attempt=$((attempt + 1))
        done
        
        if [ "$cluster_status" != "available" ]; then
            echo "Warning: RDS cluster may not be fully available yet. You may need to wait before running migrations."
        fi
    fi


    echo "RDS deployment complete!"
fi

# Storage Deployment
if confirm "Do you want to deploy S3 storage?"; then
    echo "Starting storage deployment..."
    
    # Get bucket name from user
    read -p "Enter bucket name (lowercase letters, numbers, and hyphens only): " bucket_name
    
    # Validate bucket name
    if ! [[ $bucket_name =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
        echo "Invalid bucket name. Must contain only lowercase letters, numbers, and hyphens, and cannot start or end with a hyphen."
        exit 1
    fi
    
    # Deploy storage stack with updated name
    echo "Deploying storage resources..."
    if ! sam deploy \
        --template-file deploy/template-storage.yaml \
        --stack-name ${APP_NAME}-storage \
        --region us-east-1 \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides \
            AppName="$APP_NAME" \
            BucketName="$bucket_name" \
        --no-confirm-changeset; then
        echo "Note: If you see 'No changes to deploy', this is expected if the stack is up to date."
    fi
    
    # Get bucket name from stack output
    bucket_name=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-storage \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
        --output text)
    
    # Update zappa_settings.json with S3_BUCKET_NAME environment variable
    if [ -f "zappa_settings.json" ] && command -v jq >/dev/null 2>&1; then
        echo "Updating zappa_settings.json with S3_BUCKET_NAME environment variable..."
        STAGE="${ZAPPA_STAGE:-dev}"
        jq --arg bucket "$bucket_name" \
           --arg stage "$STAGE" '
          if .[$stage] then
            .[$stage].environment_variables.S3_BUCKET_NAME = $bucket
          else
            .
          end
        ' zappa_settings.json > zappa_settings.json.tmp && mv zappa_settings.json.tmp zappa_settings.json
        echo "Updated zappa_settings.json with S3_BUCKET_NAME=$bucket_name for stage: $STAGE"
    else
        echo "Note: Please manually add S3_BUCKET_NAME=$bucket_name to zappa_settings.json environment_variables"
    fi
    
    echo "Storage deployment complete!"
    echo "Bucket name: $bucket_name"
fi

# Zappa Deployment Bucket
if confirm "Do you want to create a Zappa deployment bucket?"; then
    echo "Starting Zappa deployment bucket creation..."
    
    # Check if stack already exists and get bucket name
    existing_bucket=""
    if [ -n "${AWS_PROFILE:-}" ]; then
        existing_bucket=$(AWS_PROFILE="$AWS_PROFILE" aws cloudformation describe-stacks \
            --stack-name ${APP_NAME}-deployment-bucket \
            --region us-east-1 \
            --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
            --output text 2>/dev/null || echo "")
    else
        existing_bucket=$(aws cloudformation describe-stacks \
            --stack-name ${APP_NAME}-deployment-bucket \
            --region us-east-1 \
            --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
            --output text 2>/dev/null || echo "")
    fi
    
    if [ -n "$existing_bucket" ] && [ "$existing_bucket" != "None" ]; then
        echo "Deployment bucket stack already exists. Using existing bucket: $existing_bucket"
        deployment_bucket_name="$existing_bucket"
    else
        # Generate a unique bucket name: app_name-deployment-bucket-randomstring
        # Use a short random string to ensure uniqueness
        if command -v openssl >/dev/null 2>&1; then
            random_suffix=$(openssl rand -hex 4 | tr '[:upper:]' '[:lower:]')
        else
            # Fallback to /dev/urandom if openssl is not available
            random_suffix=$(cat /dev/urandom | tr -dc 'a-f0-9' | fold -w 8 | head -n 1)
        fi
        deployment_bucket_name="${APP_NAME}-deployment-bucket-${random_suffix}"
        
        # Ensure bucket name meets S3 requirements (max 63 chars, lowercase, etc.)
        if [ ${#deployment_bucket_name} -gt 63 ]; then
            # Truncate if too long
            max_app_len=$((63 - ${#random_suffix} - 21))  # 21 = "-deployment-bucket-"
            if [ $max_app_len -lt 1 ]; then
                echo "Error: App name too long for bucket name generation"
                exit 1
            fi
            truncated_app=$(echo "$APP_NAME" | cut -c1-$max_app_len)
            deployment_bucket_name="${truncated_app}-deployment-bucket-${random_suffix}"
        fi
        
        echo "Generated deployment bucket name: $deployment_bucket_name"
        
        # Deploy deployment bucket stack
        echo "Deploying Zappa deployment bucket..."
        if ! sam deploy \
            --template-file deploy/template-deployment-bucket.yaml \
            --stack-name ${APP_NAME}-deployment-bucket \
            --region us-east-1 \
            --capabilities CAPABILITY_IAM \
            --parameter-overrides \
                AppName="$APP_NAME" \
                BucketName="$deployment_bucket_name" \
            --no-confirm-changeset; then
            echo "Note: If you see 'No changes to deploy', this is expected if the stack is up to date."
        fi
        
        # Get bucket name from stack output to confirm
        if [ -n "${AWS_PROFILE:-}" ]; then
            deployment_bucket_name=$(AWS_PROFILE="$AWS_PROFILE" aws cloudformation describe-stacks \
                --stack-name ${APP_NAME}-deployment-bucket \
                --region us-east-1 \
                --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
                --output text 2>/dev/null || echo "$deployment_bucket_name")
        else
            deployment_bucket_name=$(aws cloudformation describe-stacks \
                --stack-name ${APP_NAME}-deployment-bucket \
                --region us-east-1 \
                --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
                --output text 2>/dev/null || echo "$deployment_bucket_name")
        fi
    fi
    
    # Update zappa_settings.json with deployment bucket name
    if [ -f "zappa_settings.json" ] && command -v jq >/dev/null 2>&1; then
        echo "Updating zappa_settings.json with deployment bucket name..."
        STAGE="${ZAPPA_STAGE:-dev}"
        jq --arg bucket "$deployment_bucket_name" \
           --arg stage "$STAGE" '
          if .[$stage] then
            .[$stage].s3_bucket = $bucket
          else
            .
          end
        ' zappa_settings.json > zappa_settings.json.tmp && mv zappa_settings.json.tmp zappa_settings.json
        echo "Updated zappa_settings.json with s3_bucket=$deployment_bucket_name for stage: $STAGE"
    else
        echo "Note: Please manually add s3_bucket=$deployment_bucket_name to zappa_settings.json for stage: ${STAGE}"
    fi
    
    echo "Zappa deployment bucket creation complete!"
    echo "Deployment bucket name: $deployment_bucket_name"
fi

# Lambda Security Group Deployment
if confirm "Do you want to deploy Lambda security group?"; then
    echo "Starting Lambda security group deployment..."
    
    # Get VPC ID using existing select_vpc function
    vpc_info=$(select_vpc) || { echo "Failed to get valid VPC ID. Exiting."; exit 1; }
    read -r vpc_id vpc_cidr <<< "$vpc_info"
    
    echo "Selected VPC ID: $vpc_id"
    
    # Get subnet selections for Lambda
    subnet_ids=$(select_subnets "$vpc_id") || { echo "Failed to get subnet data. Exiting."; exit 1; }
    read -r subnet1 subnet2 <<< "$subnet_ids"
    
    if [ -z "$subnet1" ] || [ -z "$subnet2" ]; then
        echo "Could not get two valid subnet IDs. Exiting."
        exit 1
    fi
    
    echo "Using subnets: $subnet1 and $subnet2"
    
    # Deploy Lambda security group stack
    echo "Deploying Lambda security group..."
    if ! sam deploy \
        --template-file deploy/template-lambda-sg.yaml \
        --stack-name ${APP_NAME}-lambda-sg \
        --region us-east-1 \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides \
            AppName="$APP_NAME" \
            VpcId="$vpc_id" \
        --no-confirm-changeset; then
        echo "Note: If you see 'No changes to deploy', this is expected if the stack is up to date."
    fi
    
    # Get the security group ID from the stack output
    security_group_id=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-lambda-sg \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`SecurityGroupId`].OutputValue' \
        --output text)
    
    if [ -z "$security_group_id" ]; then
        echo "Failed to get security group ID from stack output"
        exit 1
    fi
    
    echo "Created security group: $security_group_id"
    
    # Ask to update zappa_settings.json
    if confirm "Do you want to update zappa_settings.json with the new VPC configuration?"; then
        echo "Updating zappa_settings.json..."
        # Update vpc_config in zappa_settings.json using jq
        jq --arg sg "$security_group_id" \
           --arg s1 "$subnet1" \
           --arg s2 "$subnet2" '
            .dev.vpc_config = {
                "SubnetIds": [$s1, $s2],
                "SecurityGroupIds": [$sg]
            }
        ' zappa_settings.json > zappa_settings.json.tmp && mv zappa_settings.json.tmp zappa_settings.json
        
        echo "Successfully updated zappa_settings.json with new VPC configuration"
    fi
    
    echo "Lambda security group deployment complete!"
fi

# ECR Repository Deployment
if confirm "Do you want to create an ECR repository for Lambda containers?"; then
    echo "Starting ECR repository deployment..."
    
    # Deploy ECR stack
    echo "Deploying ECR repository..."
    if ! sam deploy \
        --template-file deploy/template-ecr.yaml \
        --stack-name ${APP_NAME}-ecr \
        --region us-east-1 \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
        --parameter-overrides \
            AppName="$APP_NAME" \
        --no-confirm-changeset; then
        echo "Note: If you see 'No changes to deploy', this is expected if the stack is up to date."
    fi
    
    # Get ECR repository URI from stack output
    ecr_repository_uri=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-ecr \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryUri`].OutputValue' \
        --output text)
    
    ecr_repository_name=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-ecr \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryName`].OutputValue' \
        --output text)
    
    lambda_ecr_access_role_arn=$(aws cloudformation describe-stacks \
        --stack-name ${APP_NAME}-ecr \
        --region us-east-1 \
        --query 'Stacks[0].Outputs[?OutputKey==`LambdaECRAccessRoleArn`].OutputValue' \
        --output text)
    
    if [ -z "$ecr_repository_uri" ] || [ -z "$ecr_repository_name" ]; then
        echo "Failed to get ECR repository details from stack output"
        exit 1
    fi
    
    echo "Created ECR repository: $ecr_repository_uri"
    echo "ECR repository name: $ecr_repository_name"
    echo "Lambda ECR access role: $lambda_ecr_access_role_arn"
    
    # Update zappa_settings.json with ECR repository name for push.sh
    if [ -f "zappa_settings.json" ] && command -v jq >/dev/null 2>&1; then
        echo "Updating zappa_settings.json with ECR repository name..."
        STAGE="${ZAPPA_STAGE:-dev}"
        jq --arg repo "$ecr_repository_name" \
           --arg stage "$STAGE" '
          if .[$stage] then
            .[$stage].ecr_repository_name = $repo
          else
            .
          end
        ' zappa_settings.json > zappa_settings.json.tmp && mv zappa_settings.json.tmp zappa_settings.json
        echo "Updated zappa_settings.json with ECR repository name: $ecr_repository_name"
    fi
    
    # Update settings.py with ECR details
    # COMMENTED OUT: Changes to app_name/ directory files
    # if confirm "Do you want to update settings.py with ECR repository details?"; then
    #     echo "Updating settings.py..."
    #     
    #     # Create backup of settings file if it doesn't exist
    #     [ ! -f "$SETTINGS_FILE.bak" ] && cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
    #     
    #     # Add ECR settings
    #     if grep -q "ECR_REPOSITORY_URI" "$SETTINGS_FILE"; then
    #         # Update existing setting
    #         sed -i.tmp "s|ECR_REPOSITORY_URI = .*|ECR_REPOSITORY_URI = '${ecr_repository_uri}'|" "$SETTINGS_FILE"
    #     else
    #         # Add new setting
    #         echo "" >> "$SETTINGS_FILE"
    #         echo "# ECR Repository for Lambda Containers" >> "$SETTINGS_FILE"
    #         echo "ECR_REPOSITORY_URI = '${ecr_repository_uri}'" >> "$SETTINGS_FILE"
    #     fi
    #     
    #     if grep -q "ECR_REPOSITORY_NAME" "$SETTINGS_FILE"; then
    #         # Update existing setting
    #         sed -i.tmp "s|ECR_REPOSITORY_NAME = .*|ECR_REPOSITORY_NAME = '${ecr_repository_name}'|" "$SETTINGS_FILE"
    #     else
    #         # Add new setting
    #         echo "ECR_REPOSITORY_NAME = '${ecr_repository_name}'" >> "$SETTINGS_FILE"
    #     fi
    #     
    #     rm -f "$SETTINGS_FILE.tmp"
    #     
    #     echo "Successfully updated settings.py with ECR repository details"
    # fi
    
    echo "ECR repository deployment complete!"
fi

# Example: Generic Credentials Deployment to Secrets Manager
# This is an example template for saving application credentials to AWS Secrets Manager
# Customize the fields and validation as needed for your specific use case
if confirm "Do you want to save application credentials to Secrets Manager? (Example)"; then
    echo "Starting credentials deployment example..."
    
    # Get credentials from user
    echo "Please provide the application credentials:"
    read -p "Service Name (e.g., api, database, external-service): " service_name
    read -p "API Key or Username: " api_key
    read -s -p "API Secret or Password: " api_secret
    echo ""
    read -p "Additional Config (JSON format, or press Enter to skip): " additional_config
    
    # Validate required fields
    if [ -z "$service_name" ] || [ -z "$api_key" ] || [ -z "$api_secret" ]; then
        echo "Error: Service name, API key, and API secret are required"
        exit 1
    fi
    
    # Create a safe secret name from service name
    safe_service_name=$(echo "$service_name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g')
    secret_name="${APP_NAME}/${safe_service_name}/credentials"
    
    # Build secret string
    if [ -n "$additional_config" ]; then
        # Validate JSON if provided
        if ! echo "$additional_config" | jq . >/dev/null 2>&1; then
            echo "Warning: Additional config is not valid JSON. Storing as plain text."
            secret_string="{
                \"api_key\":\"$api_key\",
                \"api_secret\":\"$api_secret\",
                \"additional_config\":\"$additional_config\"
            }"
        else
            secret_string="{
                \"api_key\":\"$api_key\",
                \"api_secret\":\"$api_secret\",
                \"additional_config\":$additional_config
            }"
        fi
    else
        secret_string="{
            \"api_key\":\"$api_key\",
            \"api_secret\":\"$api_secret\"
        }"
    fi
    
    # Save credentials to Secrets Manager
    echo "Saving credentials to AWS Secrets Manager..."
    secret_arn=$(aws secretsmanager create-secret \
        --name "$secret_name" \
        --description "${APP_NAME} ${service_name} credentials" \
        --secret-string "$secret_string" \
        --query 'ARN' --output text)
    
    echo "Credentials saved to secret: $secret_name"
    echo "Secret ARN: $secret_arn"
    
    # Update settings.py with the secret key name (not the actual secret)
    # COMMENTED OUT: Changes to app_name/ directory files
    # if confirm "Do you want to update settings.py with the secret key name?"; then
    #     echo "Updating settings.py..."
    #     
    #     # Create backup of settings file if it doesn't exist
    #     [ ! -f "$SETTINGS_FILE.bak" ] && cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
    #     
    #     # Create a settings variable name from service name
    #     setting_name=$(echo "${safe_service_name}_SECRET_KEY" | tr '[:lower:]' '[:upper:]' | sed 's/-/_/g')
    #     
    #     # Add or update the setting
    #     if grep -q "^${setting_name}" "$SETTINGS_FILE"; then
    #         # Update existing setting
    #         sed -i.tmp "s|^${setting_name} = .*|${setting_name} = '${secret_name}'|" "$SETTINGS_FILE"
    #     else
    #         # Add new setting
    #         echo "" >> "$SETTINGS_FILE"
    #         echo "# ${service_name} Credentials" >> "$SETTINGS_FILE"
    #         echo "${setting_name} = '${secret_name}'" >> "$SETTINGS_FILE"
    #     fi
    #     rm -f "$SETTINGS_FILE.tmp"
    #     
    #     echo "Successfully updated settings.py with secret key name: ${setting_name}"
    #     echo "Note: The actual secret values are stored securely in AWS Secrets Manager"
    # fi
    
    # Optionally update zappa_settings.json extra_permissions with this specific secret ARN
    if confirm "Do you want to update zappa_settings.json to allow access to this secret ARN?"; then
        echo "Updating zappa_settings.json extra_permissions for secret..."
        jq --arg arn "$secret_arn" '
          .dev.extra_permissions += [{
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            "Resource": $arn
          }]
        ' zappa_settings.json > zappa_settings.json.tmp && mv zappa_settings.json.tmp zappa_settings.json
        echo "Updated zappa_settings.json with secret ARN permission: $secret_arn"
    fi
    
    echo "Credentials deployment example complete!"
fi

echo ""
if confirm "Do you want to see instructions for initial Django project setup and management commands?"; then
    echo "if you need to create a django project, run the following command:  AWS_PROFILE=your-profile python manage.py createproject $APP_NAME"
    echo "flatten the project structure, run the following command:  mv $APP_NAME/$APP_NAME/* $APP_NAME/ and rm -rf $APP_NAME/$APP_NAME and rm -rf $APP_NAME/manage.py"
    echo "make a backup of settings.py, run the following command:  cp $APP_NAME/settings.py $APP_NAME/settings.py.bak"
    echo "copy the template settings.py from app_name/settings.py to $APP_NAME/settings.py and replace the placeholders with the actual values"
    echo "now do the migrate: AWS_PROFILE=your-profile python manage.py migrate"
    echo "now do the createsuperuser: AWS_PROFILE=your-profile python manage.py createsuperuser"
    echo "now do the collectstatic: AWS_PROFILE=your-profile python manage.py collectstatic"
    echo "now do the runserver: AWS_PROFILE=your-profile python manage.py runserver"
fi
echo "Deployment complete!"
