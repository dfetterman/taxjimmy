from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class Invoice(models.Model):
    """Model to store uploaded invoice PDFs and metadata"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]
    
    invoice_number = models.CharField(max_length=255, db_index=True)
    date = models.DateField()
    vendor_name = models.CharField(max_length=255)
    total_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    state_code = models.CharField(max_length=2, help_text="US state code (e.g., CA, NY)")
    jurisdiction = models.CharField(max_length=255, blank=True, help_text="Specific jurisdiction if applicable")
    pdf_file = models.FileField(upload_to='invoices/%Y/%m/%d/', help_text="Uploaded invoice PDF")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    ocr_job = models.ForeignKey(
        'invoice_ocr.ProcessingJob',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        help_text="Reference to OCR processing job"
    )
    raw_ocr_data = models.TextField(
        blank=True,
        null=True,
        help_text="Raw JSON response from OCR processing"
    )
    ocr_error = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if OCR processing failed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice_number']),
            models.Index(fields=['status']),
            models.Index(fields=['date']),
        ]
    
    def __str__(self):
        return f"{self.invoice_number} - {self.vendor_name} ({self.date})"


class InvoiceLineItem(models.Model):
    """Individual line items from invoices"""
    
    TAX_STATUS_CHOICES = [
        ('taxable', 'Taxable'),
        ('exempt', 'Exempt'),
        ('unknown', 'Unknown'),
    ]
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    description = models.TextField()
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        default=Decimal('1.00')
    )
    unit_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    line_total = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    tax_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        default=Decimal('0.00')
    )
    tax_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.00'))],
        default=Decimal('0.0000'),
        help_text="Tax rate as decimal (e.g., 0.0825 for 8.25%)"
    )
    tax_status = models.CharField(max_length=20, choices=TAX_STATUS_CHOICES, default='unknown')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.description[:50]} - ${self.line_total}"


class TaxDetermination(models.Model):
    """Tax verification results for invoices"""
    
    DETERMINATION_STATUS_CHOICES = [
        ('verified', 'Verified'),
        ('discrepancy', 'Discrepancy'),
        ('error', 'Error'),
    ]
    
    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name='tax_determination')
    determination_status = models.CharField(
        max_length=20, 
        choices=DETERMINATION_STATUS_CHOICES, 
        default='verified',
        db_index=True
    )
    expected_tax = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Expected tax amount based on calculations"
    )
    actual_tax = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Actual tax amount from invoice"
    )
    discrepancy_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Difference between expected and actual tax (can be negative)"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Additional notes about the determination")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['determination_status']),
        ]
    
    def __str__(self):
        return f"Tax Determination for {self.invoice.invoice_number} - {self.determination_status}"


class TaxRule(models.Model):
    """Tax rules by state/jurisdiction (for future use)"""
    
    RULE_TYPE_CHOICES = [
        ('state', 'State'),
        ('county', 'County'),
        ('city', 'City'),
        ('special', 'Special District'),
    ]
    
    state_code = models.CharField(max_length=2, db_index=True)
    jurisdiction = models.CharField(max_length=255, blank=True, help_text="County, city, or special district name")
    tax_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Tax rate as decimal (e.g., 0.0825 for 8.25%)"
    )
    effective_date = models.DateField(help_text="Date when this rule becomes effective")
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES, default='state')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['state_code', 'jurisdiction', '-effective_date']
        indexes = [
            models.Index(fields=['state_code']),
            models.Index(fields=['effective_date']),
        ]
        unique_together = [['state_code', 'jurisdiction', 'effective_date', 'rule_type']]
    
    def __str__(self):
        jurisdiction_str = f" - {self.jurisdiction}" if self.jurisdiction else ""
        return f"{self.state_code}{jurisdiction_str} - {self.tax_rate}% ({self.rule_type})"

