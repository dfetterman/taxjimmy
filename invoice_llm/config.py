"""
Configuration manager for invoice_llm app.
Reads all configuration from database models.
"""
from django.core.exceptions import ObjectDoesNotExist
from invoice_llm.models import BedrockModelConfig, ProcessingConfig
from invoice_llm.exceptions import ConfigurationError, ModelNotFoundError
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration by reading from database models."""
    
    @staticmethod
    def get_default_model():
        """
        Get the default Bedrock model configuration.
        
        Returns:
            BedrockModelConfig: Default model config
            
        Raises:
            ModelNotFoundError: If no default model is configured
        """
        try:
            model = BedrockModelConfig.objects.get(is_default=True, is_active=True)
            return model
        except BedrockModelConfig.DoesNotExist:
            # Try to get any active model
            try:
                model = BedrockModelConfig.objects.filter(is_active=True).first()
                if model:
                    logger.warning("No default model found, using first active model")
                    return model
            except Exception:
                pass
            raise ModelNotFoundError("No default or active model configured")
    
    @staticmethod
    def get_model_by_id(model_id):
        """
        Get a model configuration by model ID.
        
        Args:
            model_id: AWS Bedrock model ID
            
        Returns:
            BedrockModelConfig: Model config
            
        Raises:
            ModelNotFoundError: If model is not found
        """
        try:
            model = BedrockModelConfig.objects.get(model_id=model_id, is_active=True)
            return model
        except BedrockModelConfig.DoesNotExist:
            raise ModelNotFoundError(f"Model not found or not active: {model_id}")
    
    @staticmethod
    def get_model_by_name(name):
        """
        Get a model configuration by name.
        
        Args:
            name: Model name
            
        Returns:
            BedrockModelConfig: Model config
            
        Raises:
            ModelNotFoundError: If model is not found
        """
        try:
            model = BedrockModelConfig.objects.get(name=name, is_active=True)
            return model
        except BedrockModelConfig.DoesNotExist:
            raise ModelNotFoundError(f"Model not found or not active: {name}")
    
    @staticmethod
    def list_active_models():
        """
        Get all active model configurations.
        
        Returns:
            QuerySet: Active model configs
        """
        return BedrockModelConfig.objects.filter(is_active=True).order_by('-is_default', 'name')
    
    @staticmethod
    def get_config(key, default=None):
        """
        Get a processing configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Any: Configuration value or default
        """
        return ProcessingConfig.get_value(key, default)
    
    @staticmethod
    def set_config(key, value, description=''):
        """
        Set a processing configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value
            description: Optional description
        """
        return ProcessingConfig.set_value(key, value, description)
    
    @staticmethod
    def get_timeout():
        """Get processing timeout in seconds."""
        return ConfigManager.get_config('timeout_seconds', 300)
    
    @staticmethod
    def get_max_retries():
        """Get maximum number of retries."""
        return ConfigManager.get_config('max_retries', 3)
    
    @staticmethod
    def get_textract_config():
        """Get Textract-specific configuration."""
        return ConfigManager.get_config('textract_config', {
            'use_analyze_document': False,
            'feature_types': ['TABLES', 'FORMS'],
        })
    
    @staticmethod
    def get_bedrock_region():
        """Get default AWS region for Bedrock."""
        return ConfigManager.get_config('bedrock_region', 'us-east-1')
