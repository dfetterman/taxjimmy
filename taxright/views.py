from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.contrib import messages
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


# UI Views
@login_required
def dashboard(request):
    """Dashboard view showing invoice statistics and recent invoices"""
    invoices = Invoice.objects.all().order_by('-created_at')[:20]
    
    # Calculate statistics
    total_invoices = Invoice.objects.count()
    pending_count = Invoice.objects.filter(status='pending').count()
    completed_count = Invoice.objects.filter(status='completed').count()
    
    total_amount_result = Invoice.objects.aggregate(
        total=Sum('total_amount')
    )
    total_amount = total_amount_result['total'] or 0
    
    context = {
        'invoices': invoices,
        'total_invoices': total_invoices,
        'pending_count': pending_count,
        'completed_count': completed_count,
        'total_amount': total_amount,
    }
    
    return render(request, 'taxright/dashboard.html', context)


@login_required
def invoice_detail(request, invoice_id):
    """Detail view for a specific invoice"""
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    context = {
        'invoice': invoice,
    }
    
    return render(request, 'taxright/invoice_detail.html', context)


@login_required
def upload_invoice(request):
    """View for uploading a new invoice"""
    if request.method == 'POST':
        try:
            invoice = Invoice.objects.create(
                invoice_number=request.POST.get('invoice_number'),
                date=request.POST.get('date'),
                vendor_name=request.POST.get('vendor_name'),
                total_amount=request.POST.get('total_amount'),
                state_code=request.POST.get('state_code'),
                jurisdiction=request.POST.get('jurisdiction', ''),
                pdf_file=request.FILES.get('pdf_file'),
                status='pending'
            )
            messages.success(request, f'Invoice {invoice.invoice_number} uploaded successfully!')
            return redirect('taxright:invoice_detail', invoice_id=invoice.id)
        except Exception as e:
            messages.error(request, f'Error uploading invoice: {str(e)}')
    
    return render(request, 'taxright/upload.html')

