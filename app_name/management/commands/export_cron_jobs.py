import json
from django.core.management.base import BaseCommand
from chroniker.models import Job  # Adjust the import based on your actual model
from datetime import datetime

class Command(BaseCommand):
    help = 'Export cron jobs data to a JSON file'

    def handle(self, *args, **kwargs):
        jobs = Job.objects.all()  # Fetch all jobs
        jobs_list = []

        for job in jobs:
            job_data = {
                'id': job.id,
                'name': job.name,
                'frequency': job.frequency,
                'params': job.params,
                'command': job.command,
                'args': job.args,
                'raw_command': job.raw_command,
                'enabled': job.enabled,
                'next_run': job.next_run.isoformat() if job.next_run else None,  # Convert to ISO 8601 string
                'last_run_start_timestamp': job.last_run_start_timestamp.isoformat() if job.last_run_start_timestamp else None,
                'last_run': job.last_run.isoformat() if job.last_run else None,
                'last_heartbeat': job.last_heartbeat.isoformat() if job.last_heartbeat else None,
                'is_running': job.is_running,
                'last_run_successful': job.last_run_successful,
                'current_hostname': job.current_hostname,
                'current_pid': job.current_pid,
                'total_parts': job.total_parts,
                'total_parts_complete': job.total_parts_complete,
                # Add other fields as necessary
            }
            jobs_list.append(job_data)

        with open('cron_jobs_export.json', 'w') as f:
            json.dump(jobs_list, f, indent=4)  # Write to JSON file
        self.stdout.write(self.style.SUCCESS('Successfully exported cron jobs to cron_jobs_export.json')) 