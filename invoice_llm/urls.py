from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'models', views.BedrockModelConfigViewSet, basename='bedrock-model-config')
router.register(r'config', views.ProcessingConfigViewSet, basename='processing-config')
router.register(r'jobs', views.ProcessingJobViewSet, basename='processing-job')
router.register(r'process', views.InvoiceProcessViewSet, basename='invoice-process')

urlpatterns = [
    path('', include(router.urls)),
]
