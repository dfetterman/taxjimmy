#!/usr/bin/env python3
"""
Script to create an S3 bucket for a specified state and upload state-specific data files.

This script:
1. Creates an S3 bucket for the specified state
2. Uploads state-specific data files to the bucket

Requirements:
- AWS credentials configured (via AWS CLI, environment variables, or IAM role)
- Appropriate IAM permissions for S3
- boto3 installed

Usage:
    python upload_state_to_s3.py --state New_Jersey --region us-east-1
"""

import boto3
import argparse
from pathlib import Path
from botocore.exceptions import ClientError


class StateS3Uploader:
    """Creates S3 bucket and uploads state-specific data files."""
    
    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize the uploader with AWS clients.
        
        Args:
            region_name: AWS region for resources
        """
        self.region_name = region_name
        self.s3_client = boto3.client('s3', region_name=region_name)
    
    def create_s3_bucket(self, bucket_name: str) -> bool:
        """
        Create S3 bucket for state data files.
        
        Args:
            bucket_name: Name of the S3 bucket
            
        Returns:
            True if bucket created successfully, False otherwise
        """
        try:
            # Check if bucket exists
            try:
                self.s3_client.head_bucket(Bucket=bucket_name)
                print(f"✓ S3 bucket '{bucket_name}' already exists")
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
            
            print(f"✓ Created S3 bucket '{bucket_name}'")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'BucketAlreadyOwnedByYou':
                print(f"✓ S3 bucket '{bucket_name}' already exists")
                return True
            else:
                print(f"✗ Error creating S3 bucket: {e}")
                return False
    
    def upload_state_data_files(self, bucket_name: str, state_data_path: str, 
                                state_name: str) -> int:
        """
        Upload state-specific data files to S3 bucket.
        
        Args:
            bucket_name: Name of the S3 bucket
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
        
        # Upload files to S3 bucket
        for txt_file in txt_files:
            s3_key = f"state_data/{txt_file.name}"
            
            try:
                # Upload file to S3 bucket
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


def main():
    parser = argparse.ArgumentParser(
        description='Create S3 bucket and upload state-specific data files'
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
        '--bucket-prefix',
        type=str,
        default='state-data',
        help='Prefix for bucket name (default: state-data)'
    )
    
    args = parser.parse_args()
    
    # Resolve state_data path relative to script location
    script_dir = Path(__file__).parent
    state_data_path = script_dir / args.state_data_path
    
    # Generate bucket name (remove spaces, underscores, and hyphens)
    state_clean = args.state.replace(' ', '').replace('_', '').replace('-', '').lower()
    bucket_name = f"{args.bucket_prefix}-{state_clean}"
    
    # Ensure bucket name is valid (AWS naming requirements)
    bucket_name = bucket_name.lower()[:63]  # S3 bucket names must be lowercase and max 63 chars
    
    print("=" * 60)
    print("State Data S3 Uploader")
    print("=" * 60)
    print(f"Region: {args.region}")
    print(f"State: {args.state}")
    print(f"S3 Bucket: {bucket_name}")
    print(f"State Data Path: {state_data_path}")
    print("=" * 60)
    print()
    
    # Initialize uploader
    uploader = StateS3Uploader(region_name=args.region)
    
    # Step 1: Create S3 bucket
    print("Step 1: Creating S3 bucket...")
    if not uploader.create_s3_bucket(bucket_name):
        print("✗ Failed to create S3 bucket. Exiting.")
        return 1
    print()
    
    # Step 2: Upload state data files
    print("Step 2: Uploading state-specific data files...")
    try:
        uploaded = uploader.upload_state_data_files(
            bucket_name, str(state_data_path), args.state
        )
        if uploaded == 0:
            print("⚠ No files were uploaded. Exiting.")
            return 1
    except Exception as e:
        print(f"✗ Error uploading files: {e}")
        return 1
    print()
    
    print("=" * 60)
    print("✓ Upload Complete!")
    print("=" * 60)
    print(f"State: {args.state}")
    print(f"S3 Bucket: {bucket_name}")
    print(f"Files uploaded: {uploaded}")
    print()
    
    return 0


if __name__ == "__main__":
    exit(main())

