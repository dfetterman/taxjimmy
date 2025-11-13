from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import tempfile
import os

from .models import BedrockModelConfig, ProcessingConfig, ProcessingJob
from .serializers import (
    BedrockModelConfigSerializer,
    ProcessingConfigSerializer,
    ProcessingJobSerializer,
    InvoiceProcessSerializer,
    InvoiceProcessResponseSerializer
)
from .services import InvoiceProcessor
from .exceptions import InvoiceProcessingError


class BedrockModelConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Bedrock model configurations."""
    
    queryset = BedrockModelConfig.objects.all()
    serializer_class = BedrockModelConfigSerializer
    filterset_fields = ['is_active', 'is_default', 'region']
    search_fields = ['name', 'model_id']
    ordering_fields = ['name', 'created_at', 'is_default']
    ordering = ['-is_default', 'name']


class ProcessingConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for managing processing configurations."""
    
    queryset = ProcessingConfig.objects.all()
    serializer_class = ProcessingConfigSerializer
    search_fields = ['key', 'description']
    ordering_fields = ['key', 'updated_at']
    ordering = ['key']


class ProcessingJobViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing processing jobs (read-only)."""
    
    queryset = ProcessingJob.objects.all()
    serializer_class = ProcessingJobSerializer
    filterset_fields = ['status', 'method']
    search_fields = ['file_path', 'model_id']
    ordering_fields = ['created_at', 'completed_at']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['get'])
    def result(self, request, pk=None):
        """Get the extracted text result for a processing job."""
        job = self.get_object()
        if job.status == 'completed':
            return Response({
                'job_id': job.id,
                'extracted_text': job.extracted_text,
                'status': job.status
            })
        elif job.status == 'failed':
            return Response({
                'job_id': job.id,
                'error_message': job.error_message,
                'status': job.status
            }, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({
                'job_id': job.id,
                'status': job.status,
                'message': 'Processing not yet completed'
            }, status=status.HTTP_202_ACCEPTED)


class InvoiceProcessViewSet(viewsets.ViewSet):
    """ViewSet for processing invoices."""
    
    parser_classes = [MultiPartParser, FormParser]
    
    @action(detail=False, methods=['post'], url_path='process')
    def process_invoice(self, request):
        """
        Process an invoice PDF file.
        
        Accepts a PDF file and processes it using either Bedrock or Textract.
        """
        serializer = InvoiceProcessSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = serializer.validated_data['file']
        method = serializer.validated_data.get('method', 'bedrock')
        model_id = serializer.validated_data.get('model_id') or None
        
        # Save uploaded file temporarily
        temp_file = None
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            # Prepare processing parameters
            process_kwargs = {}
            if serializer.validated_data.get('temperature') is not None:
                process_kwargs['temperature'] = serializer.validated_data['temperature']
            if serializer.validated_data.get('max_tokens') is not None:
                process_kwargs['max_tokens'] = serializer.validated_data['max_tokens']
            if serializer.validated_data.get('prompt_template'):
                process_kwargs['prompt_template'] = serializer.validated_data['prompt_template']
            if method == 'textract' and serializer.validated_data.get('use_analyze'):
                process_kwargs['use_analyze'] = True
            
            # Process the invoice
            processor = InvoiceProcessor()
            extracted_text = processor.process_pdf(
                file_path=temp_file_path,
                method=method,
                model_id=model_id,
                create_job=True,
                **process_kwargs
            )
            
            # Get the created job
            job = ProcessingJob.objects.filter(
                file_path=temp_file_path,
                method=method
            ).order_by('-created_at').first()
            
            response_data = {
                'job_id': job.id if job else None,
                'status': 'completed',
                'extracted_text': extracted_text,
                'method': method,
                'model_id': model_id
            }
            
            response_serializer = InvoiceProcessResponseSerializer(data=response_data)
            if response_serializer.is_valid():
                return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
            else:
                return Response(response_data, status=status.HTTP_200_OK)
                
        except InvoiceProcessingError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Unexpected error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Clean up temporary file
            if temp_file and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
    
    @action(detail=False, methods=['get'])
    def models(self, request):
        """Get list of available Bedrock models."""
        models = BedrockModelConfig.objects.filter(is_active=True)
        serializer = BedrockModelConfigSerializer(models, many=True)
        return Response(serializer.data)
