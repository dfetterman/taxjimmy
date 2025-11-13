from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule
from .serializers import (
    InvoiceSerializer, 
    InvoiceLineItemSerializer, 
    TaxDeterminationSerializer,
    TaxRuleSerializer
)


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing invoices.
    
    Provides CRUD operations for invoices and supports PDF file uploads.
    """
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    parser_classes = [MultiPartParser, FormParser]
    filterset_fields = ['status', 'state_code', 'vendor_name']
    search_fields = ['invoice_number', 'vendor_name', 'state_code', 'jurisdiction']
    ordering_fields = ['date', 'uploaded_at', 'total_amount', 'created_at']
    ordering = ['-created_at']
    
    def get_serializer_context(self):
        """Add request to serializer context for generating absolute URLs"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    @action(detail=True, methods=['get'])
    def line_items(self, request, pk=None):
        """Get all line items for a specific invoice"""
        invoice = self.get_object()
        line_items = invoice.line_items.all()
        serializer = InvoiceLineItemSerializer(line_items, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def tax_determination(self, request, pk=None):
        """Get tax determination for a specific invoice"""
        invoice = self.get_object()
        try:
            determination = invoice.tax_determination
            serializer = TaxDeterminationSerializer(determination)
            return Response(serializer.data)
        except TaxDetermination.DoesNotExist:
            return Response(
                {'detail': 'No tax determination found for this invoice.'},
                status=status.HTTP_404_NOT_FOUND
            )


class InvoiceLineItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing invoice line items.
    """
    queryset = InvoiceLineItem.objects.all()
    serializer_class = InvoiceLineItemSerializer
    filterset_fields = ['invoice', 'tax_status']
    search_fields = ['description', 'invoice__invoice_number']
    ordering_fields = ['id', 'line_total', 'tax_amount']
    ordering = ['id']


class TaxDeterminationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing tax determinations.
    """
    queryset = TaxDetermination.objects.all()
    serializer_class = TaxDeterminationSerializer
    filterset_fields = ['determination_status', 'invoice']
    search_fields = ['invoice__invoice_number', 'invoice__vendor_name', 'notes']
    ordering_fields = ['created_at', 'verified_at', 'discrepancy_amount']
    ordering = ['-created_at']


class TaxRuleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing tax rules.
    """
    queryset = TaxRule.objects.all()
    serializer_class = TaxRuleSerializer
    filterset_fields = ['state_code', 'rule_type']
    search_fields = ['state_code', 'jurisdiction']
    ordering_fields = ['state_code', 'effective_date', 'tax_rate']
    ordering = ['state_code', 'jurisdiction', '-effective_date']

