from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.contrib import messages
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from decimal import Decimal
import tempfile
import os
import json

from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule, LineItemTaxVerification, StateKnowledgeBase
from .serializers import (
    InvoiceSerializer, 
    InvoiceLineItemSerializer, 
    TaxDeterminationSerializer,
    TaxRuleSerializer,
    LineItemTaxVerificationSerializer,
    StateKnowledgeBaseSerializer
)
from .services import create_invoice_from_ocr, BedrockKnowledgeBaseService
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
    
    @action(detail=True, methods=['get'], url_path='pipeline/tax-verification')
    def get_tax_verification_data(self, request, pk=None):
        """Get tax verification data for pipeline (KB-based)"""
        invoice = self.get_object()
        
        # Check if any line items have verifications
        line_item_verifications = LineItemTaxVerification.objects.filter(
            line_item__invoice=invoice
        ).select_related('line_item')
        
        if not line_item_verifications.exists():
            return Response({
                'status': 'not_started',
                'message': 'Tax verification has not been performed yet',
                'processed_at': None,
            })
        
        # Get verification data
        verifications_data = []
        for verification in line_item_verifications:
            verifications_data.append({
                'line_item_id': verification.line_item.id,
                'line_item_description': verification.line_item.description,
                'is_correct': verification.is_correct,
                'confidence_score': float(verification.confidence_score),
                'reasoning': verification.reasoning,
                'expected_tax_rate': float(verification.expected_tax_rate),
                'applied_tax_rate': float(verification.applied_tax_rate),
                'verified_at': verification.verified_at,
                'verification_details': verification.verification_details
            })
        
        # Get summary from tax determination if available
        summary = {}
        try:
            determination = invoice.tax_determination
            if determination.kb_verification_metadata:
                summary = determination.kb_verification_metadata.get('summary', {})
        except TaxDetermination.DoesNotExist:
            pass
        
        data = {
            'status': 'completed',
            'line_item_verifications': verifications_data,
            'summary': summary,
            'processed_at': line_item_verifications.first().verified_at if line_item_verifications.exists() else None,
        }
        
        return Response(data)
    
    @action(detail=True, methods=['post'], url_path='verify-taxes')
    def verify_taxes(self, request, pk=None):
        """Manually trigger tax verification for an invoice"""
        invoice = self.get_object()
        
        if not invoice.state_code or invoice.state_code == 'XX':
            return Response(
                {'error': 'Invoice does not have a valid state code'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not invoice.line_items.exists():
            return Response(
                {'error': 'Invoice has no line items to verify'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            kb_service = BedrockKnowledgeBaseService()
            result = kb_service.verify_invoice_taxes(invoice)
            
            return Response({
                'message': 'Tax verification completed',
                'summary': result['summary'],
                'line_item_verifications_count': len(result['line_item_verifications']),
                'tax_determination_id': result.get('tax_determination_id')
            })
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error during tax verification: {str(e)}")
            return Response(
                {'error': f'Tax verification failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
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


class LineItemTaxVerificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing line item tax verifications (read-only).
    """
    queryset = LineItemTaxVerification.objects.all()
    serializer_class = LineItemTaxVerificationSerializer
    filterset_fields = ['line_item', 'is_correct', 'line_item__invoice']
    search_fields = ['line_item__description', 'reasoning', 'line_item__invoice__invoice_number']
    ordering_fields = ['verified_at', 'confidence_score', 'is_correct']
    ordering = ['-verified_at']


class StateKnowledgeBaseViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing state-to-knowledge base mappings.
    """
    queryset = StateKnowledgeBase.objects.all()
    serializer_class = StateKnowledgeBaseSerializer
    filterset_fields = ['state_code', 'is_active', 'region']
    search_fields = ['state_code', 'knowledge_base_name', 'knowledge_base_id']
    ordering_fields = ['state_code', 'created_at']
    ordering = ['state_code']


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
    
    # Calculate line items total KB cost and tokens
    line_items_kb_cost = Decimal('0.00')
    line_items_kb_tokens = 0
    for item in invoice.line_items.all():
        line_items_kb_cost += item.kb_total_cost
        line_items_kb_tokens += item.kb_total_tokens
    
    context = {
        'invoice': invoice,
        'line_items_kb_cost': line_items_kb_cost,
        'line_items_kb_tokens': line_items_kb_tokens,
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
            ocr_result, ocr_usage_info = processor.process_pdf(
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
                invoice=invoice,
                ocr_usage_info=ocr_usage_info
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

