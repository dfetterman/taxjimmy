import json
from django.core.management.base import BaseCommand
from chroniker.models import Job  # Adjust the import based on your actual model
from datetime import datetime

class Command(BaseCommand):
    help = 'Import cron jobs data from a JSON file'

    def handle(self, *args, **kwargs):
        with open('cron_jobs_export.json', 'r') as f:  # Updated file name
            jobs_list = json.load(f)  # Load data from JSON file
            for job_data in jobs_list:
                # Remove the 'id' field to avoid duplicate key errors
                job_id = job_data.pop('id', None)  # Remove the ID from job_data

                # Convert specific string date fields to datetime objects if necessary
                date_fields = ['next_run', 'last_run_start_timestamp', 'last_run', 'last_heartbeat']  # Adjust this list based on your model
                for field in date_fields:
                    if field in job_data and isinstance(job_data[field], str):
                        try:
                            job_data[field] = datetime.fromisoformat(job_data[field])  # Adjust format as needed
                        except ValueError:
                            self.stdout.write(self.style.ERROR('Invalid date format for job {}: {}'.format(job_id, job_data[field])))
                            continue  # Skip this job if date format is invalid

                # Create a new Job instance without checking for existing IDs
                try:
                    Job.objects.create(**job_data)  # Create Job instance
                except Exception as e:
                    self.stdout.write(self.style.ERROR('Error importing job {}: {}'.format(job_id, str(e))))
                    continue  # Skip this job if there is an error

        self.stdout.write(self.style.SUCCESS('Successfully imported cron jobs from cron_jobs_export.json')) 