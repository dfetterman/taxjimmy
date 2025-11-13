# zappa_settings.py
import json
import os

# Load settings from JSON file
with open(os.path.join(os.path.dirname(__file__), 'zappa_settings.json'), 'r') as f:
    settings_data = json.load(f)

# Get the 'dev' stage settings
stage = os.environ.get('ZAPPA_STAGE', 'dev')
settings = settings_data.get(stage, settings_data.get('dev', {}))

# Convert nested keys to the format Zappa expects
for key, value in settings.items():
    if key == 'environment_variables':
        globals()['ENVIRONMENT_VARIABLES'] = value
    elif key == 'extra_permissions':
        globals()['EXTRA_PERMISSIONS'] = value
    elif key == 'vpc_config':
        globals()['VPC_CONFIG'] = value
    elif key == 'timeout_seconds':
        globals()['TIMEOUT_SECONDS'] = value
    elif key == 'memory_size':
        globals()['MEMORY_SIZE'] = value
    elif key == 'aws_region':
        globals()['AWS_REGION'] = value
    elif key == 'django_settings':
        globals()['DJANGO_SETTINGS'] = value
    elif key == 'app_function':
        globals()['APP_FUNCTION'] = value
    elif key == 'lambda_handler':
        globals()['LAMBDA_HANDLER'] = value
    elif key == 'runtime':
        globals()['RUNTIME'] = value
    elif key == 'keep_warm':
        globals()['KEEP_WARM'] = value
    elif key == 'slim_handler':
        globals()['SLIM_HANDLER'] = value
    elif key == 's3_bucket':
        globals()['S3_BUCKET'] = value
    elif key == 'project_name':
        globals()['PROJECT_NAME'] = value
    elif key == 'events':
        globals()['EVENTS'] = value
    else:
        # For any other keys, use as-is
        globals()[key.upper()] = value

# Add any missing attributes that Zappa might expect
if 'EXCEPTION_HANDLER' not in globals():
    EXCEPTION_HANDLER = None

if 'LOG_LEVEL' not in globals():
    LOG_LEVEL = 'INFO'

if 'DEBUG' not in globals():
    DEBUG = False

# Ensure API_STAGE is present (Zappa expects this)
if 'API_STAGE' not in globals():
    API_STAGE = stage

# Stage-derived helpers
STAGE = stage
SETTINGS_MODULE = globals().get('SETTINGS_MODULE', globals().get('DJANGO_SETTINGS'))
PROJECT_NAME = globals().get('PROJECT_NAME', 'app')
LAMBDA_NAME = globals().get('LAMBDA_NAME', f"{PROJECT_NAME}-{stage}")

# Additional safe defaults commonly referenced by handlers
ENVIRONMENT_VARIABLES = globals().get('ENVIRONMENT_VARIABLES', {})
EXTRA_PERMISSIONS = globals().get('EXTRA_PERMISSIONS', [])
VPC_CONFIG = globals().get('VPC_CONFIG', {})
TIMEOUT_SECONDS = globals().get('TIMEOUT_SECONDS', 30)
MEMORY_SIZE = globals().get('MEMORY_SIZE', 512)
BINARY_SUPPORT = globals().get('BINARY_SUPPORT', False)
BINARY_CONTENT_TYPES = globals().get('BINARY_CONTENT_TYPES', [])
METHOD_RESPONSE_HEADERS = globals().get('METHOD_RESPONSE_HEADERS', {})
INTEGRATION_RESPONSE_HEADERS = globals().get('INTEGRATION_RESPONSE_HEADERS', {})
CONTEXT_HEADER_MAPPINGS = globals().get('CONTEXT_HEADER_MAPPINGS', {})