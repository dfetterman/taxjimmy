# Migration Instructions: invoice_llm → invoice_ocr

This document provides step-by-step instructions for migrating from the `invoice_llm` app to the `invoice_ocr` app in your Django database.

## Overview

The `invoice_llm` app has been renamed to `invoice_ocr` and all Textract functionality has been removed. The app now only uses AWS Bedrock for OCR processing.

## Prerequisites

1. **Backup your database** before proceeding with any migration steps
2. Ensure you have Django migrations enabled
3. Make sure you're in a safe environment (development/staging) before applying to production

## Step 1: Remove invoice_llm from INSTALLED_APPS

The `invoice_llm` app has already been removed from `INSTALLED_APPS` in `taxjimmy/settings.py` and replaced with `invoice_ocr`. Verify this change:

```python
INSTALLED_APPS = [
    # ... other apps ...
    'invoice_ocr',  # Invoice OCR processing app with AWS Bedrock
    # ... other apps ...
]
```

## Step 2: Database Migration Steps

### Option A: Fresh Database (Development Only)

If you're in a development environment and can afford to lose data:

1. **Delete existing migrations** (optional, only if starting fresh):
   ```bash
   rm invoice_ocr/migrations/0*.py
   ```

2. **Create new initial migration**:
   ```bash
   python manage.py makemigrations invoice_ocr
   ```

3. **Apply migrations**:
   ```bash
   python manage.py migrate invoice_ocr
   ```

### Option B: Preserve Data (Production/Staging)

If you need to preserve existing data, you'll need to manually migrate the database tables:

#### 2.1: Rename Database Tables

Connect to your PostgreSQL database and run these SQL commands:

```sql
-- Rename the app's tables
ALTER TABLE invoice_llm_bedrockmodelconfig RENAME TO invoice_ocr_bedrockmodelconfig;
ALTER TABLE invoice_llm_processingconfig RENAME TO invoice_ocr_processingconfig;
ALTER TABLE invoice_llm_processingjob RENAME TO invoice_ocr_processingjob;

-- Update the django_migrations table
UPDATE django_migrations 
SET app = 'invoice_ocr' 
WHERE app = 'invoice_llm';
```

#### 2.2: Update Foreign Key References

If any other tables have foreign keys referencing `invoice_llm` tables, update them:

```sql
-- Check for foreign keys (run this first to see what needs updating)
SELECT 
    tc.table_name, 
    kcu.column_name, 
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name 
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE constraint_type = 'FOREIGN KEY' 
  AND ccu.table_name LIKE 'invoice_llm%';

-- If any foreign keys are found, update them accordingly
-- Example (adjust based on actual foreign keys found):
-- ALTER TABLE some_other_table 
--   DROP CONSTRAINT some_other_table_invoice_llm_id_fkey;
-- ALTER TABLE some_other_table 
--   ADD CONSTRAINT some_other_table_invoice_ocr_id_fkey 
--   FOREIGN KEY (invoice_ocr_id) REFERENCES invoice_ocr_processingjob(id);
```

#### 2.3: Update ProcessingJob Method Values

Since Textract has been removed, update any existing records that use 'textract' method:

```sql
-- Check for any records with 'textract' method
SELECT COUNT(*) FROM invoice_ocr_processingjob WHERE method = 'textract';

-- Update them to 'bedrock' (or delete if preferred)
UPDATE invoice_ocr_processingjob 
SET method = 'bedrock' 
WHERE method = 'textract';

-- Or delete them if you don't need to preserve Textract processing history:
-- DELETE FROM invoice_ocr_processingjob WHERE method = 'textract';
```

#### 2.4: Create and Apply Migrations

1. **Create a migration to reflect the table renames**:
   ```bash
   python manage.py makemigrations invoice_ocr --empty --name rename_tables
   ```

2. **Edit the migration file** to add the RenameModel operations:
   ```python
   from django.db import migrations

   class Migration(migrations.Migration):
       dependencies = [
           ('invoice_ocr', '0001_initial'),  # Adjust based on your migration number
       ]

       operations = [
           migrations.RenameModel(
               old_name='BedrockModelConfig',
               new_name='BedrockModelConfig',
           ),
           migrations.RenameModel(
               old_name='ProcessingConfig',
               new_name='ProcessingConfig',
           ),
           migrations.RenameModel(
               old_name='ProcessingJob',
               new_name='ProcessingJob',
           ),
       ]
   ```

   **Note**: If you've already renamed the tables manually in the database, you may need to use `migrations.RunSQL` instead or mark the migration as already applied.

3. **Fake the migration** (if tables already renamed):
   ```bash
   python manage.py migrate invoice_ocr --fake
   ```

   Or **apply normally** if not yet renamed:
   ```bash
   python manage.py migrate invoice_ocr
   ```

## Step 3: Update URL Patterns

The URL pattern has been updated in `taxjimmy/urls.py`:
- Old: `path('api/invoice-llm/', include('invoice_llm.urls'))`
- New: `path('api/invoice-ocr/', include('invoice_ocr.urls'))`

**Important**: Update any API clients or frontend code that references the old URL path.

## Step 4: Verify Migration

1. **Check that tables exist with new names**:
   ```bash
   python manage.py dbshell
   \dt invoice_ocr*
   ```

2. **Test the API endpoints**:
   ```bash
   # Test the new endpoint
   curl http://localhost:8000/api/invoice-ocr/models/
   ```

3. **Run Django checks**:
   ```bash
   python manage.py check
   ```

4. **Test invoice processing**:
   ```bash
   python manage.py test_invoice_processing /path/to/invoice.pdf
   ```

## Step 5: Clean Up (Optional)

After successful migration, you can optionally:

1. **Remove old migration files** (if you created new ones):
   ```bash
   # Keep a backup first!
   # Then remove old migrations if desired
   ```

2. **Update any documentation** that references `invoice_llm`

3. **Update environment variables** or configuration files that reference the old app name

## Troubleshooting

### Issue: "Table does not exist" errors

**Solution**: Make sure you've renamed the tables in the database. Check with:
```sql
SELECT tablename FROM pg_tables WHERE tablename LIKE 'invoice_%';
```

### Issue: Foreign key constraint errors

**Solution**: Update foreign key constraints as shown in Step 2.2

### Issue: Migration conflicts

**Solution**: 
1. Check `django_migrations` table for conflicting entries
2. You may need to manually insert/update migration records:
   ```sql
   INSERT INTO django_migrations (app, name, applied) 
   VALUES ('invoice_ocr', '0001_initial', NOW())
   ON CONFLICT DO NOTHING;
   ```

### Issue: API endpoints return 404

**Solution**: 
1. Verify URL patterns in `taxjimmy/urls.py`
2. Restart your Django development server
3. Check that `invoice_ocr` is in `INSTALLED_APPS`

## Rollback Plan

If you need to rollback:

1. **Revert code changes** (git checkout previous commit)
2. **Rename tables back**:
   ```sql
   ALTER TABLE invoice_ocr_bedrockmodelconfig RENAME TO invoice_llm_bedrockmodelconfig;
   ALTER TABLE invoice_ocr_processingconfig RENAME TO invoice_llm_processingconfig;
   ALTER TABLE invoice_ocr_processingjob RENAME TO invoice_llm_processingjob;
   ```
3. **Update INSTALLED_APPS** back to `invoice_llm`
4. **Restore from database backup** if needed

## Summary

The migration involves:
- ✅ Code changes (already completed)
- ⚠️ Database table renames (manual SQL required)
- ⚠️ URL path updates (already completed, but verify clients)
- ⚠️ Data migration for ProcessingJob.method field (SQL update)

**Important Notes**:
- Textract functionality has been completely removed
- Only Bedrock method is now supported
- All models now use `invoice_ocr` app name
- API endpoint changed from `/api/invoice-llm/` to `/api/invoice-ocr/`

