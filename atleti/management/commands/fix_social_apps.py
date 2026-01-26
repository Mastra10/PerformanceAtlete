from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site

class Command(BaseCommand):
    help = 'Rimuove le SocialApp duplicate dal database per evitare conflitti con settings.py'

    def handle(self, *args, **options):
        # Cancella tutte le app Strava dal DB
        count, _ = SocialApp.objects.filter(provider='strava').delete()
        
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f'Rimosse {count} configurazioni SocialApp (Strava) dal database.'))
            self.stdout.write(self.style.SUCCESS('Ora il sistema userà la configurazione in settings.py (.env).'))
        else:
            self.stdout.write(self.style.WARNING('Nessuna SocialApp trovata nel DB. Il problema potrebbe essere altrove o già risolto.'))