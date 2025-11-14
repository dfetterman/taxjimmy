from django.contrib import admin
from django.utils.html import format_html
from .models import BedrockModelConfig, ProcessingConfig, ProcessingJob


@admin.register(BedrockModelConfig)
class BedrockModelConfigAdmin(admin.ModelAdmin):
    """Admin interface for BedrockModelConfig model"""
    
    list_display = ('name', 'model_id', 'region', 'is_default', 'is_active', 'max_tokens', 'temperature', 'created_at')
    list_filter = ('is_default', 'is_active', 'region', 'created_at')
    search_fields = ('name', 'model_id', 'region')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Model Information', {
            'fields': ('name', 'model_id', 'region', 'is_default', 'is_active')
        }),
        ('Model Parameters', {
            'fields': ('max_tokens', 'temperature', 'top_p', 'prompt_template')
        }),
        ('Pricing', {
            'fields': ('input_token_cost', 'output_token_cost'),
            'description': 'Cost per 1K tokens (e.g., 0.003 for $0.003 per thousand)'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make created_at and updated_at readonly"""
        return self.readonly_fields
    
    actions = ['make_default', 'activate', 'deactivate']
    
    def make_default(self, request, queryset):
        """Set selected models as default (only one can be default)"""
        count = queryset.update(is_default=True)
        # Ensure only one is default
        if count > 0:
            # Unset default for all others
            BedrockModelConfig.objects.filter(is_default=True).exclude(
                pk__in=queryset.values_list('pk', flat=True)
            ).update(is_default=False)
        self.message_user(request, f'{count} model(s) set as default.')
    make_default.short_description = "Set selected models as default"
    
    def activate(self, request, queryset):
        """Activate selected models"""
        count = queryset.update(is_active=True)
        self.message_user(request, f'{count} model(s) activated.')
    activate.short_description = "Activate selected models"
    
    def deactivate(self, request, queryset):
        """Deactivate selected models"""
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} model(s) deactivated.')
    deactivate.short_description = "Deactivate selected models"


@admin.register(ProcessingConfig)
class ProcessingConfigAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingConfig model"""
    
    list_display = ('key', 'value_preview', 'description', 'updated_at')
    list_filter = ('updated_at', 'created_at')
    search_fields = ('key', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Configuration', {
            'fields': ('key', 'value', 'description')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def value_preview(self, obj):
        """Display a preview of the JSON value"""
        import json
        value_str = json.dumps(obj.value) if obj.value else ''
        if len(value_str) > 50:
            return format_html('<span title="{}">{}</span>', value_str, value_str[:50] + '...')
        return value_str
    value_preview.short_description = 'Value'


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingJob model"""
    
    list_display = ('id', 'status_badge', 'method', 'model_id', 'file_path_short', 'created_at', 'completed_at', 'duration')
    list_filter = ('status', 'method', 'created_at', 'completed_at')
    search_fields = ('file_path', 'model_id', 'error_message', 'extracted_text')
    readonly_fields = ('id', 'created_at', 'updated_at', 'completed_at', 'extracted_text_preview', 'metadata_display', 'usage_info')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Job Information', {
            'fields': ('id', 'file_path', 'method', 'model_id', 'status')
        }),
        ('Results', {
            'fields': ('extracted_text_preview', 'error_message', 'usage_info')
        }),
        ('Metadata', {
            'fields': ('metadata_display',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        """Display status with color coding"""
        colors = {
            'pending': 'orange',
            'processing': 'blue',
            'completed': 'green',
            'failed': 'red',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def file_path_short(self, obj):
        """Display shortened file path"""
        if len(obj.file_path) > 50:
            return format_html('<span title="{}">{}</span>', obj.file_path, obj.file_path[:50] + '...')
        return obj.file_path
    file_path_short.short_description = 'File Path'
    
    def extracted_text_preview(self, obj):
        """Display preview of extracted text"""
        if not obj.extracted_text:
            return "No text extracted"
        text = obj.extracted_text[:500] if len(obj.extracted_text) > 500 else obj.extracted_text
        return format_html('<pre style="max-height: 300px; overflow-y: auto; white-space: pre-wrap;">{}</pre>', text)
    extracted_text_preview.short_description = 'Extracted Text Preview'
    
    def metadata_display(self, obj):
        """Display metadata in a readable format"""
        import json
        if not obj.metadata:
            return "No metadata"
        return format_html('<pre>{}</pre>', json.dumps(obj.metadata, indent=2))
    metadata_display.short_description = 'Metadata'
    
    def usage_info(self, obj):
        """Display token usage and cost information"""
        if not obj.metadata or 'usage' not in obj.metadata:
            return "No usage information available"
        
        usage = obj.metadata['usage']
        return format_html(
            '<table style="border-collapse: collapse; width: 100%;">'
            '<tr><th style="text-align: left; padding: 5px;">Metric</th><th style="text-align: right; padding: 5px;">Value</th></tr>'
            '<tr><td style="padding: 5px;">Input Tokens:</td><td style="text-align: right; padding: 5px;">{:,}</td></tr>'
            '<tr><td style="padding: 5px;">Output Tokens:</td><td style="text-align: right; padding: 5px;">{:,}</td></tr>'
            '<tr><td style="padding: 5px;">Total Tokens:</td><td style="text-align: right; padding: 5px;">{:,}</td></tr>'
            '<tr><td style="padding: 5px;">Input Cost:</td><td style="text-align: right; padding: 5px;">${:.8f}</td></tr>'
            '<tr><td style="padding: 5px;">Output Cost:</td><td style="text-align: right; padding: 5px;">${:.8f}</td></tr>'
            '<tr><td style="padding: 5px; font-weight: bold;">Total Cost:</td><td style="text-align: right; padding: 5px; font-weight: bold;">${:.8f}</td></tr>'
            '</table>',
            usage.get('inputTokens', 0),
            usage.get('outputTokens', 0),
            usage.get('totalTokens', 0),
            usage.get('inputCost', 0.0),
            usage.get('outputCost', 0.0),
            usage.get('totalCost', 0.0)
        )
    usage_info.short_description = 'Token Usage & Cost'
    
    def duration(self, obj):
        """Calculate and display processing duration"""
        if obj.completed_at and obj.created_at:
            delta = obj.completed_at - obj.created_at
            seconds = delta.total_seconds()
            if seconds < 60:
                return f"{seconds:.2f}s"
            elif seconds < 3600:
                return f"{seconds/60:.2f}m"
            else:
                return f"{seconds/3600:.2f}h"
        return "-"
    duration.short_description = 'Duration'
    
    actions = ['retry_failed_jobs']
    
    def retry_failed_jobs(self, request, queryset):
        """Mark failed jobs for retry (reset status to pending)"""
        count = queryset.filter(status='failed').update(status='pending', error_message='')
        self.message_user(request, f'{count} failed job(s) marked for retry.')
    retry_failed_jobs.short_description = "Retry selected failed jobs"

