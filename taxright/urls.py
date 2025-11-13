from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InvoiceViewSet,
    InvoiceLineItemViewSet,
    TaxDeterminationViewSet,
    TaxRuleViewSet
)

# Create a router and register our viewsets with it
router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'invoice-line-items', InvoiceLineItemViewSet, basename='invoice-line-item')
router.register(r'tax-determinations', TaxDeterminationViewSet, basename='tax-determination')
router.register(r'tax-rules', TaxRuleViewSet, basename='tax-rule')

app_name = 'taxright'

urlpatterns = [
    # API routes
    path('api/', include(router.urls)),
]

