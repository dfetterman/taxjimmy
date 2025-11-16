from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
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
    total_tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        default=Decimal('0.00'),
        help_text="Total tax amount from invoice (when tax is shown as total, not per-line-item)"
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
    # OCR token and cost tracking
    ocr_input_tokens = models.IntegerField(
        default=0,
        help_text="Number of input tokens used for OCR processing"
    )
    ocr_output_tokens = models.IntegerField(
        default=0,
        help_text="Number of output tokens used for OCR processing"
    )
    ocr_total_tokens = models.IntegerField(
        default=0,
        help_text="Total tokens used for OCR processing (input + output)"
    )
    ocr_input_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Cost for OCR input tokens (in USD)"
    )
    ocr_output_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Cost for OCR output tokens (in USD)"
    )
    ocr_total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total cost for OCR processing (in USD)"
    )
    total_llm_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total LLM cost (OCR + all line item KB verification costs) in USD"
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
    
    def recalculate_total_llm_cost(self):
        """Recalculate total_llm_cost from OCR cost + sum of all line item KB costs"""
        from django.db.models import Sum
        line_items_total = self.line_items.aggregate(
            total=Sum('kb_total_cost')
        )['total'] or Decimal('0.00')
        self.total_llm_cost = self.ocr_total_cost + line_items_total
        self.save(update_fields=['total_llm_cost', 'updated_at'])


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
    # KB verification token and cost tracking
    kb_input_tokens = models.IntegerField(
        default=0,
        help_text="Number of input tokens used for KB verification of this line item"
    )
    kb_output_tokens = models.IntegerField(
        default=0,
        help_text="Number of output tokens used for KB verification of this line item"
    )
    kb_total_tokens = models.IntegerField(
        default=0,
        help_text="Total tokens used for KB verification (input + output)"
    )
    kb_input_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Cost for KB verification input tokens (in USD)"
    )
    kb_output_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Cost for KB verification output tokens (in USD)"
    )
    kb_total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total cost for KB verification of this line item (in USD)"
    )
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
    kb_verification_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Metadata from Bedrock KB verification (KB ID, query details, etc.)"
    )
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


class StateKnowledgeBase(models.Model):
    """Mapping of US states to Bedrock Knowledge Base IDs"""
    
    state_code = models.CharField(max_length=2, unique=True, db_index=True, help_text="US state code (e.g., CA, NY)")
    knowledge_base_id = models.CharField(max_length=255, help_text="AWS Bedrock Knowledge Base ID")
    knowledge_base_name = models.CharField(max_length=255, help_text="Human-readable KB name")
    region = models.CharField(max_length=50, default='us-east-1', help_text="AWS region for the knowledge base")
    is_active = models.BooleanField(default=True, help_text="Whether this KB mapping is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['state_code']
        indexes = [
            models.Index(fields=['state_code', 'is_active']),
        ]
    
    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.state_code} -> {self.knowledge_base_name} ({status})"


class LineItemTaxVerification(models.Model):
    """Tax verification results for individual line items using Bedrock KB"""
    
    line_item = models.ForeignKey(InvoiceLineItem, on_delete=models.CASCADE, related_name='tax_verifications')
    is_correct = models.BooleanField(help_text="Whether the applied tax is correct according to state law")
    confidence_score = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text="Confidence score from 0.00 to 1.00"
    )
    reasoning = models.TextField(help_text="Explanation of why the tax is correct or incorrect")
    expected_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Expected tax rate based on state law (as decimal, e.g., 0.0825 for 8.25%)"
    )
    applied_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Tax rate that was actually applied (as decimal)"
    )
    verification_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional verification metadata (KB query details, citations, etc.)"
    )
    verified_at = models.DateTimeField(auto_now_add=True, help_text="When this verification was performed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-verified_at']
        indexes = [
            models.Index(fields=['line_item', 'is_correct']),
            models.Index(fields=['verified_at']),
        ]
    
    def __str__(self):
        status = "Correct" if self.is_correct else "Incorrect"
        return f"Verification for {self.line_item.description[:30]}... - {status} ({self.confidence_score})"

