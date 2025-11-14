from django.contrib import admin
from .models import BedrockModelConfig, ProcessingConfig, ProcessingJob


@admin.register(BedrockModelConfig)
class BedrockModelConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'model_id', 'region', 'input_token_cost', 'output_token_cost', 'is_default', 'is_active', 'created_at']
    list_filter = ['is_default', 'is_active', 'region']
    search_fields = ['name', 'model_id']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'model_id', 'region', 'is_default', 'is_active')
        }),
        ('Model Parameters', {
            'fields': ('max_tokens', 'temperature', 'top_p')
        }),
        ('Pricing', {
            'fields': ('input_token_cost', 'output_token_cost'),
            'description': 'Cost per 1,000 tokens (e.g., 0.003 for $0.003 per thousand input tokens)'
        }),
        ('Prompt Template', {
            'fields': ('prompt_template',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ProcessingConfig)
class ProcessingConfigAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'description', 'updated_at']
    search_fields = ['key', 'description']
    fieldsets = (
        ('Configuration', {
            'fields': ('key', 'value', 'description')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'method', 'model_id', 'status', 'created_at', 'completed_at']
    list_filter = ['status', 'method', 'created_at']
    search_fields = ['file_path', 'model_id', 'extracted_text']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']
    fieldsets = (
        ('Job Information', {
            'fields': ('file_path', 'method', 'model_id', 'status')
        }),
        ('Results', {
            'fields': ('extracted_text', 'error_message', 'metadata')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Disable manual creation of processing jobs."""
        return False
