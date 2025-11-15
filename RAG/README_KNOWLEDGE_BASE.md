# Bedrock Knowledge Base Setup with S3 Vector Buckets

This script creates an Amazon Bedrock Knowledge Base with S3 Vector Bucket storage for state-specific tax data.

## Prerequisites

1. **AWS Credentials**: Configure AWS credentials using one of:
   - AWS CLI: `aws configure`
   - Environment variables: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
   - IAM role (if running on EC2/Lambda)

2. **Required IAM Permissions**:
   - S3: CreateBucket, PutObject, GetObject, ListBucket
   - S3 Vectors: CreateVectorBucket, CreateIndex, PutVector, GetVector, QueryVectors
   - Bedrock: CreateKnowledgeBase, ListKnowledgeBases
   - IAM: CreateRole, PutRolePolicy, GetRole

3. **Python Dependencies**:
   - boto3 (already in requirements.txt)

## Usage

### Basic Usage

```bash
cd RAG
python create_bedrock_knowledge_base.py --state New_Jersey
```

### Full Example

```bash
python create_bedrock_knowledge_base.py \
  --state New_Jersey \
  --region us-east-1 \
  --embedding-model amazon.titan-embed-text-v1
```

### State Name Format

The state name should match the prefix of your state data files. For example:
- `New_Jersey` matches files like `New_Jersey1.txt`, `New_Jersey2.txt`, etc.
- `California` matches files like `California1.txt`, `California2.txt`, etc.
- `New York` (with space) will be normalized to `New_York`

## What the Script Does

1. **Creates S3 Vector Bucket**: Creates a new vector bucket for each run
   - Bucket name includes timestamp and UUID for uniqueness
   - Format: `state-kb-{state}-{timestamp}-{uuid}`

2. **Creates Vector Index**: Creates an index within the vector bucket
   - Uses 1536 dimensions (default for Amazon Titan embeddings)
   - Uses COSINE similarity metric

3. **Uploads State Data**: Uploads state-specific `.txt` files
   - Filters files by state name prefix
   - Uploads to `s3://bucket-name/state_data/`
   - Only files matching the state name are uploaded

4. **Creates IAM Role**: Creates a role for Bedrock to access:
   - S3 bucket (read access for source data)
   - S3 Vector Bucket (read/write access for vectors)

5. **Creates Knowledge Base**: Creates the Bedrock Knowledge Base
   - Uses S3 Vector Bucket as the vector store
   - Connects to S3 for source data files
   - Configures vector embeddings using Amazon Titan

## Command Line Options

- `--state` (required): State name (e.g., "New_Jersey", "California", "New York")
- `--region`: AWS region (default: us-east-1)
- `--state-data-path`: Path to state_data directory (default: state_data)
- `--embedding-model`: Embedding model ID (default: amazon.titan-embed-text-v1)

## Important Notes

### New Resources on Each Run

- **Each run creates NEW resources** (bucket, KB, IAM role)
- Resource names include timestamp and UUID for uniqueness
- This allows you to create multiple KBs for the same state
- Old resources are NOT deleted automatically

### One State Per Run

- Specify one state per run using `--state`
- Only files matching that state name will be uploaded
- Each state gets its own bucket and knowledge base

### File Naming

State data files should be named with the state as a prefix:
- ✅ `New_Jersey1.txt`, `New_Jersey2.txt` (matches `--state New_Jersey`)
- ✅ `California1.txt`, `California2.txt` (matches `--state California`)
- ❌ `NJ1.txt` (won't match `--state New_Jersey`)

## After Running

1. **Check Knowledge Base Status**: Go to AWS Bedrock Console → Knowledge Bases
2. **Wait for Sync**: The knowledge base will automatically start syncing data
3. **Query the Knowledge Base**: Use the Bedrock API or console to query your state data

## Example: Creating KBs for Multiple States

```bash
# Create KB for New Jersey
python create_bedrock_knowledge_base.py --state New_Jersey

# Create KB for California
python create_bedrock_knowledge_base.py --state California

# Create KB for New York
python create_bedrock_knowledge_base.py --state "New_York"
```

Each command creates a separate knowledge base with its own bucket and resources.

## Troubleshooting

### No Files Found

If you see "No files found matching state", check:
1. State name matches file prefixes exactly (case-sensitive)
2. Files are in the `state_data/` directory
3. Files have `.txt` extension

### Bucket Already Exists

If you get "BucketAlreadyExists" error:
- This is rare since names include timestamps
- Wait a moment and try again, or use a different state name

### IAM Role Already Exists

If you get "EntityAlreadyExists" for IAM role:
- This is rare since names include timestamps
- Wait a moment and try again

### Storage Configuration

If you get errors about storage configuration:
- Verify that S3 Vector Buckets are available in your region
- Check that your AWS account has access to S3 Vectors service
- The storage type `S3_VECTOR` may need to be verified against latest AWS documentation

## Cost Considerations

- **S3**: Storage costs for your data files
- **S3 Vector Buckets**: Charges based on storage and operations
- **Bedrock**: Charges for embedding model usage and knowledge base queries

See AWS pricing pages for current rates.

## Cleanup

To clean up resources created by this script:
1. Delete the Knowledge Base in Bedrock Console
2. Delete the S3 Vector Bucket (via AWS Console or CLI)
3. Delete the IAM role (via IAM Console or CLI)
4. Delete the regular S3 bucket if it was created separately

Note: The script does NOT automatically delete old resources. You must clean them up manually.
