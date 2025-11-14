from rest_framework import serializers
from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    """Serializer for InvoiceLineItem model"""
    
    class Meta:
        model = InvoiceLineItem
        fields = [
            'id', 'invoice', 'description', 'quantity', 'unit_price', 
            'line_total', 'tax_amount', 'tax_rate', 'tax_status',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer for Invoice model"""
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    pdf_file_url = serializers.SerializerMethodField()
    ocr_job_id = serializers.IntegerField(source='ocr_job.id', read_only=True, allow_null=True)
    has_ocr_data = serializers.SerializerMethodField()
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'date', 'vendor_name', 'total_amount',
            'state_code', 'jurisdiction', 'pdf_file', 'pdf_file_url',
            'status', 'uploaded_at', 'processed_at', 'line_items',
            'ocr_job_id', 'raw_ocr_data', 'ocr_error', 'has_ocr_data',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'uploaded_at', 'created_at', 'updated_at']
    
    def get_pdf_file_url(self, obj):
        """Return the URL of the PDF file"""
        if obj.pdf_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.pdf_file.url)
            return obj.pdf_file.url
        return None
    
    def get_has_ocr_data(self, obj):
        """Check if invoice has OCR data"""
        return bool(obj.raw_ocr_data or obj.ocr_job)


class TaxDeterminationSerializer(serializers.ModelSerializer):
    """Serializer for TaxDetermination model"""
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    invoice_vendor = serializers.CharField(source='invoice.vendor_name', read_only=True)
    
    class Meta:
        model = TaxDetermination
        fields = [
            'id', 'invoice', 'invoice_number', 'invoice_vendor',
            'determination_status', 'expected_tax', 'actual_tax',
            'discrepancy_amount', 'verified_at', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaxRuleSerializer(serializers.ModelSerializer):
    """Serializer for TaxRule model"""
    
    class Meta:
        model = TaxRule
        fields = [
            'id', 'state_code', 'jurisdiction', 'tax_rate',
            'effective_date', 'rule_type', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

