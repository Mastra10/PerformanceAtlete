from django.core.management.base import BaseCommand
from atleti.tasks import task_sync_strava

class Command(BaseCommand):
    help = 'Esegue manualmente la sincronizzazione Strava per tutti gli utenti (chiama task_sync_strava)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Avvio sincronizzazione massiva Strava (task_sync_strava)..."))
        try:
            task_sync_strava()
            self.stdout.write(self.style.SUCCESS("Sincronizzazione completata. Controlla i log di sistema per i dettagli su ogni utente."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore critico: {e}"))