from django.contrib import admin
from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule, StateKnowledgeBase, LineItemTaxVerification


class InvoiceLineItemInline(admin.TabularInline):
    """Inline admin for InvoiceLineItem within Invoice admin"""
    model = InvoiceLineItem
    extra = 0
    fields = ('description', 'quantity', 'unit_price', 'line_total', 'tax_amount', 'tax_rate', 'tax_status')
    readonly_fields = ()


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Admin interface for Invoice model"""
    list_display = ('invoice_number', 'vendor_name', 'date', 'total_amount', 'state_code', 'status', 'uploaded_at')
    list_filter = ('status', 'state_code', 'date', 'uploaded_at')
    search_fields = ('invoice_number', 'vendor_name', 'state_code', 'jurisdiction')
    readonly_fields = ('created_at', 'updated_at', 'uploaded_at')
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'date', 'vendor_name', 'total_amount')
        }),
        ('Location', {
            'fields': ('state_code', 'jurisdiction')
        }),
        ('File', {
            'fields': ('pdf_file',)
        }),
        ('Status', {
            'fields': ('status', 'uploaded_at', 'processed_at')
        }),
        ('OCR Processing', {
            'fields': ('ocr_job', 'raw_ocr_data', 'ocr_error'),
            'classes': ('collapse',)
        }),
        ('LLM Costs', {
            'fields': (
                'ocr_input_tokens', 'ocr_output_tokens', 'ocr_total_tokens',
                'ocr_input_cost', 'ocr_output_cost', 'ocr_total_cost',
                'total_llm_cost'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    inlines = [InvoiceLineItemInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    """Admin interface for InvoiceLineItem model"""
    list_display = ('invoice', 'description', 'quantity', 'unit_price', 'line_total', 'tax_amount', 'tax_rate', 'tax_status', 'kb_total_cost')
    list_filter = ('tax_status', 'invoice__status', 'invoice__state_code')
    search_fields = ('description', 'invoice__invoice_number', 'invoice__vendor_name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Line Item Information', {
            'fields': ('invoice', 'description', 'quantity', 'unit_price', 'line_total')
        }),
        ('Tax Information', {
            'fields': ('tax_amount', 'tax_rate', 'tax_status')
        }),
        ('LLM KB Verification Costs', {
            'fields': (
                'kb_input_tokens', 'kb_output_tokens', 'kb_total_tokens',
                'kb_input_cost', 'kb_output_cost', 'kb_total_cost'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TaxDetermination)
class TaxDeterminationAdmin(admin.ModelAdmin):
    """Admin interface for TaxDetermination model"""
    list_display = ('invoice', 'determination_status', 'expected_tax', 'actual_tax', 'discrepancy_amount', 'verified_at')
    list_filter = ('determination_status', 'verified_at')
    search_fields = ('invoice__invoice_number', 'invoice__vendor_name', 'notes')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Invoice', {
            'fields': ('invoice',)
        }),
        ('Determination', {
            'fields': ('determination_status', 'expected_tax', 'actual_tax', 'discrepancy_amount', 'verified_at')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TaxRule)
class TaxRuleAdmin(admin.ModelAdmin):
    """Admin interface for TaxRule model"""
    list_display = ('state_code', 'jurisdiction', 'tax_rate', 'rule_type', 'effective_date')
    list_filter = ('state_code', 'rule_type', 'effective_date')
    search_fields = ('state_code', 'jurisdiction')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Rule Information', {
            'fields': ('state_code', 'jurisdiction', 'rule_type', 'tax_rate', 'effective_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(StateKnowledgeBase)
class StateKnowledgeBaseAdmin(admin.ModelAdmin):
    """Admin interface for StateKnowledgeBase model"""
    list_display = ('state_code', 'knowledge_base_name', 'knowledge_base_id', 'region', 'is_active', 'created_at')
    list_filter = ('is_active', 'region', 'created_at')
    search_fields = ('state_code', 'knowledge_base_name', 'knowledge_base_id')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Knowledge Base Mapping', {
            'fields': ('state_code', 'knowledge_base_id', 'knowledge_base_name', 'region', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(LineItemTaxVerification)
class LineItemTaxVerificationAdmin(admin.ModelAdmin):
    """Admin interface for LineItemTaxVerification model"""
    list_display = ('line_item', 'is_correct', 'confidence_score', 'expected_tax_rate', 'applied_tax_rate', 'verified_at')
    list_filter = ('is_correct', 'verified_at', 'line_item__invoice__state_code')
    search_fields = ('line_item__description', 'reasoning', 'line_item__invoice__invoice_number')
    readonly_fields = ('created_at', 'updated_at', 'verified_at')
    fieldsets = (
        ('Line Item', {
            'fields': ('line_item',)
        }),
        ('Verification Results', {
            'fields': ('is_correct', 'confidence_score', 'reasoning', 'expected_tax_rate', 'applied_tax_rate', 'verified_at')
        }),
        ('Details', {
            'fields': ('verification_details',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

