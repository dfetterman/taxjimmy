BUCKET_NAME=state-kb-vector-alabama-20251114-214708-33b2a714
DATA_BUCKET_NAME=state-kb-data-alabama-20251114-213353-19502db0
INDEX_NAME=alabama-index


AWS_PROFILE=aws-danefett-dev-isc-awsIAMShibbFull aws s3vectors delete-index --vector-bucket-name $BUCKET_NAME --index-name $INDEX_NAME
AWS_PROFILE=aws-danefett-dev-isc-awsIAMShibbFull aws s3vectors delete-vector-bucket --vector-bucket-name $BUCKET_NAME

# AWS CLI COMMANDS TO PURGE A BUCKET AND DELETE IT
AWS_PROFILE=aws-danefett-dev-isc-awsIAMShibbFull aws s3 rb s3://$DATA_BUCKET_NAME --force 