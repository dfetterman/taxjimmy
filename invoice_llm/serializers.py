from rest_framework import serializers
from .models import BedrockModelConfig, ProcessingConfig, ProcessingJob
from .services import InvoiceProcessor


class BedrockModelConfigSerializer(serializers.ModelSerializer):
    """Serializer for BedrockModelConfig."""
    
    class Meta:
        model = BedrockModelConfig
        fields = ['id', 'name', 'model_id', 'region', 'max_tokens', 'temperature', 
                 'top_p', 'prompt_template', 'is_default', 'is_active', 
                 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ProcessingConfigSerializer(serializers.ModelSerializer):
    """Serializer for ProcessingConfig."""
    
    class Meta:
        model = ProcessingConfig
        fields = ['id', 'key', 'value', 'description', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class ProcessingJobSerializer(serializers.ModelSerializer):
    """Serializer for ProcessingJob."""
    
    class Meta:
        model = ProcessingJob
        fields = ['id', 'file_path', 'method', 'model_id', 'status', 
                 'extracted_text', 'error_message', 'metadata', 
                 'created_at', 'updated_at', 'completed_at']
        read_only_fields = ['id', 'status', 'extracted_text', 'error_message', 
                          'metadata', 'created_at', 'updated_at', 'completed_at']


class InvoiceProcessSerializer(serializers.Serializer):
    """Serializer for invoice processing request."""
    
    file = serializers.FileField(required=True, help_text="PDF invoice file")
    method = serializers.ChoiceField(
        choices=['bedrock', 'textract'],
        default='bedrock',
        help_text="Processing method"
    )
    model_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Bedrock model ID (optional, uses default if not specified)"
    )
    temperature = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Temperature for LLM (0.0-1.0)"
    )
    max_tokens = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=8192,
        help_text="Maximum tokens in response"
    )
    prompt_template = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Custom prompt template"
    )
    use_analyze = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Use Textract analyze_document (for tables/forms)"
    )
    
    def validate_file(self, value):
        """Validate uploaded file."""
        if not value.name.lower().endswith('.pdf'):
            raise serializers.ValidationError("File must be a PDF")
        if value.size > 50 * 1024 * 1024:  # 50MB
            raise serializers.ValidationError("File size must be less than 50MB")
        return value


class InvoiceProcessResponseSerializer(serializers.Serializer):
    """Serializer for invoice processing response."""
    
    job_id = serializers.IntegerField(help_text="Processing job ID")
    status = serializers.CharField(help_text="Processing status")
    extracted_text = serializers.CharField(help_text="Extracted invoice text")
    method = serializers.CharField(help_text="Processing method used")
    model_id = serializers.CharField(required=False, allow_null=True, help_text="Model ID used")
