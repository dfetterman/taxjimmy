#!/usr/bin/env python3
"""
Script to create Amazon Bedrock Knowledge Base with S3 Vector Bucket
for state-specific tax data.

This script:
1. Creates an S3 Vector Bucket for a specific state
2. Uploads state-specific data files to the bucket
3. Creates IAM role for Bedrock to access S3 Vector Bucket
4. Creates a Bedrock Knowledge Base using the S3 Vector Bucket

Requirements:
- AWS credentials configured (via AWS CLI, environment variables, or IAM role)
- Appropriate IAM permissions for S3, S3 Vectors, Bedrock, and IAM
- boto3 installed

Usage:
    python create_bedrock_knowledge_base.py --state New_Jersey --region us-east-1
"""

import boto3
import os
import json
import time
import argparse
import uuid
from datetime import datetime
from pathlib import Path
from botocore.exceptions import ClientError
from typing import Optional, Dict, Any, List


class BedrockKnowledgeBaseCreator:
    """Creates Bedrock Knowledge Base with S3 Vector Bucket storage."""
    
    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize the creator with AWS clients.
        
        Args:
            region_name: AWS region for resources
        """
        self.region_name = region_name
        self.s3_client = boto3.client('s3', region_name=region_name)
        self.s3vectors_client = boto3.client('s3vectors', region_name=region_name)
        self.bedrock_client = boto3.client('bedrock-agent', region_name=region_name)
        self.bedrock_runtime = boto3.client('bedrock-agent-runtime', region_name=region_name)
        self.iam_client = boto3.client('iam', region_name=region_name)
        self.account_id = boto3.client('sts').get_caller_identity()['Account']
        
    def generate_unique_name(self, prefix: str, state_name: str) -> str:
        """
        Generate a unique name with timestamp and UUID.
        
        Args:
            prefix: Prefix for the name
            state_name: State name to include
            
        Returns:
            Unique name string
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        state_clean = state_name.replace(' ', '_').replace('-', '_')
        return f"{prefix}-{state_clean}-{timestamp}-{unique_id}"
    
    def create_s3_vector_bucket(self, bucket_name: str) -> bool:
        """
        Create S3 Vector Bucket for vector storage.
        
        Args:
            bucket_name: Name of the S3 Vector Bucket
            
        Returns:
            True if bucket created successfully, False otherwise
        """
        try:
            print(f"Creating S3 Vector Bucket '{bucket_name}'...")
            
            response = self.s3vectors_client.create_vector_bucket(
                vectorBucketName=bucket_name
            )
            
            print(f"✓ Created S3 Vector Bucket '{bucket_name}'")
            print(f"  Bucket ARN: {response.get('bucketArn', 'N/A')}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'BucketAlreadyExists':
                print(f"✗ S3 Vector Bucket '{bucket_name}' already exists")
                print(f"  Note: This script creates new buckets on each run. Please use a different state or wait.")
                return False
            else:
                print(f"✗ Error creating S3 Vector Bucket: {e}")
                return False
    
    def create_vector_index(self, bucket_name: str, index_name: str) -> Optional[str]:
        """
        Create a vector index within the S3 Vector Bucket.
        
        Args:
            bucket_name: Name of the S3 Vector Bucket
            index_name: Name of the index
            
        Returns:
            Index ARN if successful, None otherwise. If ARN is not in response,
            constructs it using the standard format.
        """
        try:
            print(f"Creating vector index '{index_name}' in bucket '{bucket_name}'...")
            
            response = self.s3vectors_client.create_index(
                vectorBucketName=bucket_name,
                indexName=index_name,
                dataType='float32',  # Data type for vector values
                dimension=1536,  # Default dimension for Amazon Titan embeddings
                distanceMetric='cosine'  # Cosine similarity metric
            )
            
            index_arn = response.get('indexArn', '')
            
            # If ARN is not in response, construct it using standard format
            if not index_arn:
                index_arn = f'arn:aws:s3vectors:{self.region_name}:{self.account_id}:vector-bucket/{bucket_name}/index/{index_name}'
            
            print(f"✓ Created vector index '{index_name}'")
            print(f"  Index ARN: {index_arn}")
            return index_arn
            
        except ClientError as e:
            print(f"✗ Error creating vector index: {e}")
            return None
    
    def create_s3_data_bucket(self, bucket_name: str) -> bool:
        """
        Create regular S3 bucket for source data files.
        
        Args:
            bucket_name: Name of the S3 bucket
            
        Returns:
            True if bucket created successfully, False otherwise
        """
        try:
            # Check if bucket exists
            try:
                self.s3_client.head_bucket(Bucket=bucket_name)
                print(f"✓ S3 data bucket '{bucket_name}' already exists")
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    # Bucket doesn't exist, create it
                    pass
                else:
                    raise
            
            # Create bucket
            if self.region_name == 'us-east-1':
                self.s3_client.create_bucket(Bucket=bucket_name)
            else:
                self.s3_client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region_name}
                )
            
            # Block public access
            self.s3_client.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )
            
            print(f"✓ Created S3 data bucket '{bucket_name}'")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'BucketAlreadyOwnedByYou':
                print(f"✓ S3 data bucket '{bucket_name}' already exists")
                return True
            else:
                print(f"✗ Error creating S3 data bucket: {e}")
                return False
    
    def upload_state_data_files(self, bucket_name: str, index_name: str, 
                                state_data_path: str, state_name: str) -> int:
        """
        Upload state-specific data files to regular S3 bucket.
        Note: Source data goes to regular S3, vectors go to S3 Vector Bucket.
        
        Args:
            bucket_name: Name of the regular S3 bucket for source data
            index_name: Name of the vector index (not used here, for compatibility)
            state_data_path: Path to the state_data directory
            state_name: Name of the state to filter files
            
        Returns:
            Number of files uploaded
        """
        state_data_dir = Path(state_data_path)
        if not state_data_dir.exists():
            raise FileNotFoundError(f"State data directory not found: {state_data_path}")
        
        # Normalize state name for matching (handle variations)
        state_normalized = state_name.replace(' ', '_').replace('-', '_')
        state_variations = [
            state_normalized,
            state_name.replace('_', ' '),
            state_name.replace('_', '-'),
        ]
        
        # Get all .txt files matching the state name
        txt_files = []
        for txt_file in state_data_dir.glob("*.txt"):
            file_name = txt_file.stem  # filename without extension
            # Check if file starts with any variation of the state name
            if any(file_name.startswith(variation) for variation in state_variations):
                txt_files.append(txt_file)
        
        if not txt_files:
            print(f"⚠ No files found matching state '{state_name}' in {state_data_path}")
            print(f"  Looking for files starting with: {', '.join(state_variations)}")
            return 0
        
        uploaded_count = 0
        
        print(f"\nUploading {len(txt_files)} state-specific files to S3...")
        
        # Upload files to regular S3 bucket (source data for Bedrock KB)
        for txt_file in txt_files:
            s3_key = f"state_data/{txt_file.name}"
            
            try:
                # Upload file to regular S3 bucket
                self.s3_client.upload_file(
                    str(txt_file),
                    bucket_name,
                    s3_key,
                    ExtraArgs={'ContentType': 'text/plain'}
                )
                uploaded_count += 1
                
                if uploaded_count % 10 == 0:
                    print(f"  Uploaded {uploaded_count} files...")
                    
            except ClientError as e:
                print(f"✗ Error uploading {txt_file.name}: {e}")
        
        print(f"✓ Uploaded {uploaded_count} files")
        return uploaded_count
    
    def create_iam_role(self, role_name: str, data_bucket_name: str, vector_bucket_name: str) -> Optional[str]:
        """
        Create IAM role for Bedrock Knowledge Base.
        
        Args:
            role_name: Name of the IAM role
            data_bucket_name: Name of the regular S3 bucket for source data
            vector_bucket_name: Name of the S3 Vector Bucket
            
        Returns:
            Role ARN if successful, None otherwise
        """
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "aws:SourceAccount": self.account_id
                        }
                    }
                }
            ]
        }
        
        # Policy for S3 (source data) and S3 Vector Bucket access
        s3_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:ListBucket"
                    ],
                    "Resource": [
                        f"arn:aws:s3:::{data_bucket_name}",
                        f"arn:aws:s3:::{data_bucket_name}/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3vectors:GetVector",
                        "s3vectors:PutVector",
                        "s3vectors:QueryVectors",
                        "s3vectors:ListVectors",
                        "s3vectors:GetIndex",
                        "s3vectors:ListIndexes"
                    ],
                    "Resource": [
                        f"arn:aws:s3vectors:{self.region_name}:{self.account_id}:vector-bucket/{vector_bucket_name}",
                        f"arn:aws:s3vectors:{self.region_name}:{self.account_id}:vector-bucket/{vector_bucket_name}/*"
                    ]
                }
            ]
        }
        
        try:
            # Create role (always create new role with unique name)
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"IAM role for Bedrock Knowledge Base to access S3 and S3 Vector Bucket"
            )
            role_arn = response['Role']['Arn']
            
            # Attach inline policy
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-s3-policy",
                PolicyDocument=json.dumps(s3_policy)
            )
            
            # Wait a moment for role to propagate
            time.sleep(2)
            
            print(f"✓ Created IAM role '{role_name}'")
            return role_arn
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'EntityAlreadyExists':
                print(f"✗ IAM role '{role_name}' already exists")
                print(f"  Note: This script creates new roles on each run.")
                return None
            else:
                print(f"✗ Error creating IAM role: {e}")
                return None
    
    def create_knowledge_base(self, kb_name: str, data_bucket_name: str, vector_bucket_name: str,
                              role_arn: str, index_name: str, index_arn: Optional[str] = None,
                              embedding_model: str = "amazon.titan-embed-text-v1") -> Optional[str]:
        """
        Create Bedrock Knowledge Base using S3 Vector Bucket.
        
        Args:
            kb_name: Name of the knowledge base
            data_bucket_name: Name of the regular S3 bucket for source data
            vector_bucket_name: Name of the S3 Vector Bucket
            role_arn: ARN of the IAM role
            index_name: Name of the vector index
            embedding_model: Embedding model ID (default: amazon.titan-embed-text-v1)
            
        Returns:
            Knowledge Base ID if successful, None otherwise
        """
        try:
            print(f"Creating Bedrock Knowledge Base '{kb_name}'...")
            
            # Build s3VectorsConfiguration
            s3_vectors_config = {
                'vectorBucketArn': f'arn:aws:s3vectors:{self.region_name}:{self.account_id}:vector-bucket/{vector_bucket_name}',
                'indexName': index_name
            }
            # Add indexArn if available
            if index_arn:
                s3_vectors_config['indexArn'] = index_arn
            
            # Create knowledge base with S3 Vector Bucket storage
            response = self.bedrock_client.create_knowledge_base(
                name=kb_name,
                description=f"Knowledge base for {vector_bucket_name} state tax data using S3 Vector Bucket",
                roleArn=role_arn,
                knowledgeBaseConfiguration={
                    'type': 'VECTOR',
                    'vectorKnowledgeBaseConfiguration': {
                        'embeddingModelArn': f'arn:aws:bedrock:{self.region_name}::foundation-model/{embedding_model}'
                    }
                },
                storageConfiguration={
                    'type': 'S3_VECTOR',
                    's3VectorsConfiguration': s3_vectors_config
                }
            )
            
            kb_id = response['knowledgeBase']['knowledgeBaseId']
            
            # Create data source separately (data sources are added after KB creation)
            print(f"  Creating data source for S3 bucket '{data_bucket_name}'...")
            try:
                data_source_response = self.bedrock_client.create_data_source(
                    knowledgeBaseId=kb_id,
                    name=f"{kb_name}-data-source",
                    dataSourceConfiguration={
                        'type': 'S3',
                        's3Configuration': {
                            'bucketArn': f'arn:aws:s3:::{data_bucket_name}',
                            'inclusionPrefixes': ['state_data/']
                        }
                    }
                )
                print(f"✓ Created data source: {data_source_response['dataSource']['dataSourceId']}")
            except ClientError as e:
                print(f"⚠ Warning: Could not create data source automatically: {e}")
                print(f"  You may need to create it manually in the AWS console")
            print(f"✓ Created Knowledge Base '{kb_name}' (ID: {kb_id})")
            print(f"  Note: The knowledge base will start syncing data. This may take some time.")
            
            return kb_id
            
        except ClientError as e:
            print(f"✗ Error creating Knowledge Base: {e}")
            print(f"  Error details: {e.response}")
            return None


def main():
    parser = argparse.ArgumentParser(
        description='Create Bedrock Knowledge Base with S3 Vector Bucket for state-specific data'
    )
    parser.add_argument(
        '--state',
        type=str,
        required=True,
        help='State name (e.g., "New_Jersey", "California", "New York")'
    )
    parser.add_argument(
        '--region',
        type=str,
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--state-data-path',
        type=str,
        default='state_data',
        help='Path to state_data directory (default: state_data)'
    )
    parser.add_argument(
        '--embedding-model',
        type=str,
        default='amazon.titan-embed-text-v1',
        help='Embedding model ID (default: amazon.titan-embed-text-v1)'
    )
    
    args = parser.parse_args()
    
    # Resolve state_data path relative to script location
    script_dir = Path(__file__).parent
    state_data_path = script_dir / args.state_data_path
    
    # Generate unique names for this run
    creator = BedrockKnowledgeBaseCreator(region_name=args.region)
    
    state_clean = args.state.replace(' ', '_').replace('-', '_').lower()
    vector_bucket_name = creator.generate_unique_name('state-kb-vector', state_clean)
    data_bucket_name = creator.generate_unique_name('state-kb-data', state_clean)
    kb_name = creator.generate_unique_name('bedrock-kb', state_clean)
    role_name = creator.generate_unique_name('bedrock-kb-role', state_clean)
    index_name = f"{state_clean}-index"
    
    # Ensure bucket names and role name are valid (AWS naming requirements)
    vector_bucket_name = vector_bucket_name.lower()[:63]  # S3 bucket names must be lowercase and max 63 chars
    data_bucket_name = data_bucket_name.lower()[:63]
    role_name = role_name[:64]  # IAM role names max 64 chars
    index_name = index_name.lower()  # S3 Vector index names must be lowercase
    
    print("=" * 60)
    print("Bedrock Knowledge Base Creator (S3 Vector Buckets)")
    print("=" * 60)
    print(f"Region: {args.region}")
    print(f"State: {args.state}")
    print(f"S3 Vector Bucket: {vector_bucket_name}")
    print(f"S3 Data Bucket: {data_bucket_name}")
    print(f"Vector Index: {index_name}")
    print(f"Knowledge Base: {kb_name}")
    print(f"IAM Role: {role_name}")
    print(f"State Data Path: {state_data_path}")
    print("=" * 60)
    print()
    
    # Step 1: Create S3 Vector Bucket
    print("Step 1: Creating S3 Vector Bucket...")
    if not creator.create_s3_vector_bucket(vector_bucket_name):
        print("✗ Failed to create S3 Vector Bucket. Exiting.")
        return 1
    print()
    
    # Step 2: Create Vector Index
    print("Step 2: Creating vector index...")
    index_arn = creator.create_vector_index(vector_bucket_name, index_name)
    if not index_arn:
        print("✗ Failed to create vector index. Exiting.")
        return 1
    print()
    
    # Step 3: Create regular S3 bucket for source data
    print("Step 3: Creating S3 data bucket...")
    if not creator.create_s3_data_bucket(data_bucket_name):
        print("✗ Failed to create S3 data bucket. Exiting.")
        return 1
    print()
    
    # Step 4: Upload state data files
    print("Step 4: Uploading state-specific data files...")
    try:
        uploaded = creator.upload_state_data_files(
            data_bucket_name, index_name, str(state_data_path), args.state
        )
        if uploaded == 0:
            print("⚠ No files were uploaded. Exiting.")
            return 1
    except Exception as e:
        print(f"✗ Error uploading files: {e}")
        return 1
    print()
    
    # Step 5: Create IAM role
    print("Step 5: Creating IAM role...")
    role_arn = creator.create_iam_role(role_name, data_bucket_name, vector_bucket_name)
    if not role_arn:
        print("✗ Failed to create IAM role. Exiting.")
        return 1
    print()
    
    # Step 6: Create Knowledge Base
    print("Step 6: Creating Bedrock Knowledge Base...")
    kb_id = creator.create_knowledge_base(
        kb_name, data_bucket_name, vector_bucket_name, role_arn, index_name, index_arn, args.embedding_model
    )
    if not kb_id:
        print("✗ Failed to create Knowledge Base. Exiting.")
        return 1
    print()
    
    print("=" * 60)
    print("✓ Setup Complete!")
    print("=" * 60)
    print(f"State: {args.state}")
    print(f"Knowledge Base ID: {kb_id}")
    print(f"Knowledge Base Name: {kb_name}")
    print(f"S3 Vector Bucket: {vector_bucket_name}")
    print(f"S3 Data Bucket: {data_bucket_name}")
    print(f"Vector Index: {index_name}")
    print(f"IAM Role: {role_name}")
    print()
    print("Note: The knowledge base will automatically start syncing data.")
    print("You can check the sync status in the AWS Bedrock console.")
    print()
    
    return 0


if __name__ == "__main__":
    exit(main())
