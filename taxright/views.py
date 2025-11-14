from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.contrib import messages
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
import tempfile
import os
import json

from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule
from .serializers import (
    InvoiceSerializer, 
    InvoiceLineItemSerializer, 
    TaxDeterminationSerializer,
    TaxRuleSerializer
)
from .services import create_invoice_from_ocr
from invoice_ocr.services import InvoiceProcessor
from invoice_ocr.exceptions import InvoiceProcessingError


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
    
    @action(detail=True, methods=['get'], url_path='pipeline/ocr')
    def get_ocr_data(self, request, pk=None):
        """Get OCR processing data for pipeline"""
        invoice = self.get_object()
        
        data = {
            'status': 'not_started',
            'extracted_text': None,
            'raw_data': None,
            'error': None,
            'processed_at': None,
            'job_id': None,
        }
        
        if invoice.ocr_job:
            data['status'] = invoice.ocr_job.status
            data['extracted_text'] = invoice.ocr_job.extracted_text
            data['job_id'] = invoice.ocr_job.id
            data['processed_at'] = invoice.ocr_job.completed_at
        
        if invoice.raw_ocr_data:
            data['raw_data'] = invoice.raw_ocr_data
        
        if invoice.ocr_error:
            data['error'] = invoice.ocr_error
            data['status'] = 'error'
        
        if invoice.status == 'completed' and not invoice.ocr_error:
            data['status'] = 'completed'
            data['processed_at'] = invoice.processed_at
        
        return Response(data)
    
    @action(detail=True, methods=['get'], url_path='pipeline/tax-db')
    def get_tax_db_data(self, request, pk=None):
        """Get tax database processing data for pipeline (placeholder)"""
        invoice = self.get_object()
        
        # Placeholder - functionality not developed yet
        data = {
            'status': 'not_implemented',
            'message': 'Tax database processing is not yet implemented',
            'processed_at': None,
        }
        
        return Response(data)
    
    @action(detail=True, methods=['get'], url_path='pipeline/tax-determination')
    def get_tax_determination_data(self, request, pk=None):
        """Get tax determination data for pipeline"""
        invoice = self.get_object()
        
        try:
            determination = invoice.tax_determination
            serializer = TaxDeterminationSerializer(determination)
            data = serializer.data
            data['status'] = 'completed'
            return Response(data)
        except TaxDetermination.DoesNotExist:
            return Response({
                'status': 'not_started',
                'message': 'Tax determination has not been performed yet',
            })


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
    """View for uploading a new invoice PDF and processing via OCR"""
    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            messages.error(request, 'Please select a PDF file to upload.')
            return render(request, 'taxright/upload.html')
        
        # Validate file type
        if not pdf_file.name.lower().endswith('.pdf'):
            messages.error(request, 'Only PDF files are allowed.')
            return render(request, 'taxright/upload.html')
        
        temp_file_path = None
        invoice = None
        try:
            # Save uploaded file temporarily for OCR processing
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                for chunk in pdf_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            # Reset file pointer for saving to S3
            pdf_file.seek(0)
            
            # Create invoice with processing status
            invoice = Invoice.objects.create(
                invoice_number='TEMP',  # Will be updated from OCR
                date=timezone.now().date(),
                vendor_name='Processing...',
                total_amount=0,
                state_code='XX',
                pdf_file=pdf_file,
                status='processing'
            )
            
            # Process via OCR
            processor = InvoiceProcessor()
            ocr_result = processor.process_pdf(
                file_path=temp_file_path,
                method='bedrock',
                create_job=True
            )
            
            # Get the created job
            from invoice_ocr.models import ProcessingJob
            ocr_job = ProcessingJob.objects.filter(
                file_path=temp_file_path,
                method='bedrock'
            ).order_by('-created_at').first()
            
            # Parse OCR result and update invoice data
            invoice = create_invoice_from_ocr(
                ocr_json=ocr_result,
                pdf_file=pdf_file,
                ocr_job=ocr_job,
                invoice=invoice
            )
            
            messages.success(request, f'Invoice {invoice.invoice_number} processed successfully!')
            return redirect('taxright:invoice_detail', invoice_id=invoice.id)
            
        except InvoiceProcessingError as e:
            if invoice:
                invoice.status = 'error'
                invoice.ocr_error = str(e)
                invoice.save()
                messages.error(request, f'OCR processing failed: {str(e)}')
                return redirect('taxright:invoice_detail', invoice_id=invoice.id)
            else:
                messages.error(request, f'OCR processing failed: {str(e)}')
                return render(request, 'taxright/upload.html')
        except ValueError as e:
            if invoice:
                invoice.status = 'error'
                invoice.ocr_error = f'Data parsing error: {str(e)}'
                invoice.save()
                messages.error(request, f'Error parsing invoice data: {str(e)}')
                return redirect('taxright:invoice_detail', invoice_id=invoice.id)
            else:
                messages.error(request, f'Error parsing invoice data: {str(e)}')
                return render(request, 'taxright/upload.html')
        except Exception as e:
            if invoice:
                invoice.status = 'error'
                invoice.ocr_error = str(e)
                invoice.save()
                messages.error(request, f'Unexpected error: {str(e)}')
                return redirect('taxright:invoice_detail', invoice_id=invoice.id)
            else:
                messages.error(request, f'Unexpected error: {str(e)}')
                return render(request, 'taxright/upload.html')
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
    
    return render(request, 'taxright/upload.html')

