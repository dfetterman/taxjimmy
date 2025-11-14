from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import json


class BedrockModelConfig(models.Model):
    """Store LLM model configurations in database."""
    
    name = models.CharField(max_length=255, unique=True, help_text="Human-readable model name")
    model_id = models.CharField(max_length=255, unique=True, help_text="AWS Bedrock model ID (e.g., anthropic.claude-3-sonnet-20240229-v1:0)")
    region = models.CharField(max_length=50, default='us-east-1', help_text="AWS region for the model")
    max_tokens = models.IntegerField(default=4096, validators=[MinValueValidator(1), MaxValueValidator(8192)], help_text="Maximum tokens in response")
    temperature = models.FloatField(default=0.7, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], help_text="Temperature for generation (0.0-1.0)")
    top_p = models.FloatField(default=0.9, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], help_text="Top-p sampling parameter")
    prompt_template = models.TextField(blank=True, help_text="Default prompt template for this model")
    input_token_cost = models.DecimalField(max_digits=10, decimal_places=8, default=0.0, help_text="Cost per 1K input tokens (e.g., 0.003 for $0.003 per thousand)")
    output_token_cost = models.DecimalField(max_digits=10, decimal_places=8, default=0.0, help_text="Cost per 1K output tokens (e.g., 0.015 for $0.015 per thousand)")
    is_default = models.BooleanField(default=False, help_text="Whether this is the default model")
    is_active = models.BooleanField(default=True, help_text="Whether this model is active and available")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_default', 'name']
        indexes = [
            models.Index(fields=['model_id']),
            models.Index(fields=['is_active', 'is_default']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.model_id})"
    
    def save(self, *args, **kwargs):
        # Ensure only one default model
        if self.is_default:
            BedrockModelConfig.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class ProcessingConfig(models.Model):
    """Store processing settings in database."""
    
    key = models.CharField(max_length=255, unique=True, help_text="Configuration key")
    value = models.JSONField(help_text="Configuration value (can be string, number, object, array)")
    description = models.TextField(blank=True, help_text="Description of this configuration")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['key']
        indexes = [
            models.Index(fields=['key']),
        ]
    
    def __str__(self):
        return f"{self.key} = {self.value}"
    
    @classmethod
    def get_value(cls, key, default=None):
        """Get a configuration value by key."""
        try:
            config = cls.objects.get(key=key)
            return config.value
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def set_value(cls, key, value, description=''):
        """Set a configuration value."""
        config, created = cls.objects.get_or_create(key=key, defaults={'value': value, 'description': description})
        if not created:
            config.value = value
            if description:
                config.description = description
            config.save()
        return config


class ProcessingJob(models.Model):
    """Track processing requests for logging and auditing."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    METHOD_CHOICES = [
        ('bedrock', 'AWS Bedrock'),
        ('textract', 'AWS Textract'),
    ]
    
    file_path = models.CharField(max_length=1000, help_text="Path to the processed file")
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, help_text="Processing method used")
    model_id = models.CharField(max_length=255, blank=True, null=True, help_text="Model ID used (if Bedrock)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    extracted_text = models.TextField(blank=True, help_text="Extracted text from the invoice")
    error_message = models.TextField(blank=True, help_text="Error message if processing failed")
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional metadata about the processing")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['method']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"ProcessingJob {self.id} - {self.method} - {self.status}"
