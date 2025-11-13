<!-- 28bd3fe1-7bb5-4b6c-9038-04913aa7a550 a33510e8-1b02-469e-a690-a425072c03b3 -->
# TaxRight Django App Framework Setup

## Overview

Create a new Django app `taxright` within the existing `taxjimmy` project to provide the basic framework for processing PDF invoices and making sales tax determinations. This will include models, admin interface, views, URLs, and REST API endpoints without implementing the actual PDF processing or tax calculation logic.

## Implementation Steps

### 1. Create Django App Structure

- Create `taxright` app directory with standard Django app structure:
        - `__init__.py`
        - `apps.py` - App configuration
        - `models.py` - Data models
        - `admin.py` - Admin interface
        - `views.py` - View classes/functions
        - `urls.py` - URL routing
        - `serializers.py` - DRF serializers
        - `tests.py` - Test structure
        - `migrations/__init__.py` - Migrations directory

### 2. Define Core Models (taxright/models.py)

Create placeholder models for:

- **Invoice**: Store uploaded invoice PDFs and metadata (invoice number, date, vendor, total amount, state/jurisdiction, status, uploaded_at, processed_at)
- **InvoiceLineItem**: Individual line items from invoices (invoice FK, description, quantity, unit_price, line_total, tax_amount, tax_rate, tax_status)
- **TaxDetermination**: Tax verification results (invoice FK, determination_status, expected_tax, actual_tax, discrepancy_amount, verified_at, notes)
- **TaxRule**: Future use for tax rules by state/jurisdiction (state_code, jurisdiction, tax_rate, effective_date, rule_type)

All models should include:

- Standard Django fields (id, created_at, updated_at)
- Proper ForeignKey relationships
- FileField for PDF storage (using S3 backend)
- Status fields using CharField with choices

### 3. Configure Admin Interface (taxright/admin.py)

- Register all models with Django admin
- Create admin classes with list_display, list_filter, search_fields
- Add inline admin for InvoiceLineItem within Invoice admin
- Configure file upload handling for PDFs

### 4. Create REST API (taxright/serializers.py, views.py)

- **Serializers**: Create DRF serializers for all models
- **ViewSets**: Create ViewSets for Invoice, InvoiceLineItem, TaxDetermination
- **URLs**: Configure API routes using DRF router
- Include standard CRUD operations
- Add file upload endpoint for Invoice PDFs

### 5. Create Views and URLs (taxright/views.py, urls.py)

- Create basic view structure (can be empty placeholders for now)
- Set up URL patterns for the app
- Include REST API URLs

### 6. Update Project Configuration

- Add `taxright` to `INSTALLED_APPS` in `taxjimmy/settings.py`
- Add `taxright.urls` to main URL configuration in `taxjimmy/urls.py`
- Update logging configuration to include `taxright` logger

### 7. Create Initial Migration

- Generate migration files (but don't run migrations yet - user will do this)

## Files to Create/Modify

**New Files:**

- `taxright/__init__.py`
- `taxright/apps.py`
- `taxright/models.py`
- `taxright/admin.py`
- `taxright/views.py`
- `taxright/urls.py`
- `taxright/serializers.py`
- `taxright/tests.py`
- `taxright/migrations/__init__.py`

**Files to Modify:**

- `taxjimmy/settings.py` - Add `taxright` to INSTALLED_APPS and logging
- `taxjimmy/urls.py` - Include `taxright.urls`

## Model Structure Summary

```
Invoice
  - invoice_number, date, vendor_name, total_amount
  - state_code, jurisdiction
  - pdf_file (FileField)
  - status (choices: pending, processing, completed, error)
  - timestamps

InvoiceLineItem
  - invoice (ForeignKey)
  - description, quantity, unit_price, line_total
  - tax_amount, tax_rate
  - tax_status (choices: taxable, exempt, unknown)

TaxDetermination
  - invoice (ForeignKey)
  - determination_status (choices: verified, discrepancy, error)
  - expected_tax, actual_tax, discrepancy_amount
  - verified_at, notes

TaxRule (for future use)
  - state_code, jurisdiction, tax_rate
  - effective_date, rule_type
```

## Notes

- All file uploads will use Django's FileField which integrates with the S3 storage backend already configured
- Models include placeholder status fields that can be expanded later
- REST API follows DRF patterns already used in the framework
- Admin interface provides immediate visibility into data
- No actual PDF processing or tax calculation logic will be implemented at this stage

### To-dos

- [ ] Create taxright Django app directory structure with all standard files (__init__.py, apps.py, models.py, admin.py, views.py, urls.py, serializers.py, tests.py, migrations/)
- [ ] Define core models: Invoice, InvoiceLineItem, TaxDetermination, TaxRule with appropriate fields, relationships, and choices
- [ ] Configure Django admin interface for all models with list_display, filters, and inline admin for line items
- [ ] Create DRF serializers for all models to support REST API
- [ ] Create ViewSets and configure REST API endpoints with router
- [ ] Create taxright/urls.py with API routes and update taxjimmy/urls.py to include taxright URLs
- [ ] Add taxright to INSTALLED_APPS and logging configuration in taxjimmy/settings.py
- [ ] Generate initial migration files for the new models