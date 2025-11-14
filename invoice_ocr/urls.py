from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BedrockModelConfigViewSet,
    ProcessingConfigViewSet,
    ProcessingJobViewSet,
    InvoiceProcessViewSet,
)

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'models', BedrockModelConfigViewSet, basename='bedrock-model-config')
router.register(r'config', ProcessingConfigViewSet, basename='processing-config')
router.register(r'jobs', ProcessingJobViewSet, basename='processing-job')
router.register(r'invoice', InvoiceProcessViewSet, basename='invoice-process')

app_name = 'invoice_ocr'

urlpatterns = [
    path('', include(router.urls)),
]

