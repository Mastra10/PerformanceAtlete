from django.core.management.base import BaseCommand
from django_apscheduler.models import DjangoJobExecution

class Command(BaseCommand):
    help = "Cancella i log di esecuzione dello scheduler dal database."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Giorni di storico da mantenere (default: 7)'
        )

    def handle(self, *args, **options):
        days = options['days']
        # Conversione in secondi
        max_age = days * 24 * 60 * 60
        
        self.stdout.write(f"Eliminazione log più vecchi di {days} giorni...")
        
        DjangoJobExecution.objects.delete_old_job_executions(max_age)
        
        self.stdout.write(self.style.SUCCESS("Pulizia completata."))