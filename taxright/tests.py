from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from decimal import Decimal
from .models import Invoice, InvoiceLineItem, TaxDetermination, TaxRule


class InvoiceModelTest(TestCase):
    """Test cases for Invoice model"""
    
    def setUp(self):
        """Set up test data"""
        self.invoice = Invoice.objects.create(
            invoice_number='INV-001',
            date='2024-01-15',
            vendor_name='Test Vendor',
            total_amount=Decimal('1000.00'),
            state_code='CA',
            jurisdiction='Los Angeles',
            status='pending'
        )
    
    def test_invoice_creation(self):
        """Test invoice creation"""
        self.assertEqual(self.invoice.invoice_number, 'INV-001')
        self.assertEqual(self.invoice.vendor_name, 'Test Vendor')
        self.assertEqual(self.invoice.status, 'pending')
    
    def test_invoice_str(self):
        """Test invoice string representation"""
        expected_str = "INV-001 - Test Vendor (2024-01-15)"
        self.assertEqual(str(self.invoice), expected_str)


class InvoiceLineItemModelTest(TestCase):
    """Test cases for InvoiceLineItem model"""
    
    def setUp(self):
        """Set up test data"""
        self.invoice = Invoice.objects.create(
            invoice_number='INV-001',
            date='2024-01-15',
            vendor_name='Test Vendor',
            total_amount=Decimal('1000.00'),
            state_code='CA',
            status='pending'
        )
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test Item',
            quantity=Decimal('2.00'),
            unit_price=Decimal('100.00'),
            line_total=Decimal('200.00'),
            tax_amount=Decimal('16.50'),
            tax_rate=Decimal('0.0825'),
            tax_status='taxable'
        )
    
    def test_line_item_creation(self):
        """Test line item creation"""
        self.assertEqual(self.line_item.description, 'Test Item')
        self.assertEqual(self.line_item.quantity, Decimal('2.00'))
        self.assertEqual(self.line_item.tax_status, 'taxable')
    
    def test_line_item_relationship(self):
        """Test line item relationship to invoice"""
        self.assertEqual(self.line_item.invoice, self.invoice)
        self.assertIn(self.line_item, self.invoice.line_items.all())


class TaxDeterminationModelTest(TestCase):
    """Test cases for TaxDetermination model"""
    
    def setUp(self):
        """Set up test data"""
        self.invoice = Invoice.objects.create(
            invoice_number='INV-001',
            date='2024-01-15',
            vendor_name='Test Vendor',
            total_amount=Decimal('1000.00'),
            state_code='CA',
            status='completed'
        )
        self.determination = TaxDetermination.objects.create(
            invoice=self.invoice,
            determination_status='verified',
            expected_tax=Decimal('82.50'),
            actual_tax=Decimal('82.50'),
            discrepancy_amount=Decimal('0.00')
        )
    
    def test_determination_creation(self):
        """Test tax determination creation"""
        self.assertEqual(self.determination.determination_status, 'verified')
        self.assertEqual(self.determination.expected_tax, Decimal('82.50'))
        self.assertEqual(self.determination.discrepancy_amount, Decimal('0.00'))
    
    def test_determination_relationship(self):
        """Test determination relationship to invoice"""
        self.assertEqual(self.determination.invoice, self.invoice)
        self.assertEqual(self.invoice.tax_determination, self.determination)


class TaxRuleModelTest(TestCase):
    """Test cases for TaxRule model"""
    
    def setUp(self):
        """Set up test data"""
        self.tax_rule = TaxRule.objects.create(
            state_code='CA',
            jurisdiction='Los Angeles',
            tax_rate=Decimal('0.0825'),
            effective_date='2024-01-01',
            rule_type='city'
        )
    
    def test_tax_rule_creation(self):
        """Test tax rule creation"""
        self.assertEqual(self.tax_rule.state_code, 'CA')
        self.assertEqual(self.tax_rule.jurisdiction, 'Los Angeles')
        self.assertEqual(self.tax_rule.tax_rate, Decimal('0.0825'))
        self.assertEqual(self.tax_rule.rule_type, 'city')

