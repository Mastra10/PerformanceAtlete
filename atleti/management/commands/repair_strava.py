from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialApp, SocialToken
from django.contrib.sites.models import Site
import os

class Command(BaseCommand):
    help = 'Ripara la configurazione Strava: crea SocialApp se manca e ricollega i token orfani'

    def handle(self, *args, **options):
        self.stdout.write("--- AVVIO RIPARAZIONE STRAVA ---")

        # 1. Cerca o Crea la SocialApp
        app = SocialApp.objects.filter(provider='strava').first()
        
        if not app:
            self.stdout.write("⚠️ SocialApp Strava non trovata. Creazione in corso...")
            client_id = os.environ.get('STRAVA_CLIENT_ID')
            secret = os.environ.get('STRAVA_CLIENT_SECRET')
            
            if not client_id or not secret:
                self.stdout.write(self.style.ERROR("❌ ERRORE: STRAVA_CLIENT_ID o STRAVA_CLIENT_SECRET mancanti nel file .env"))
                return

            app = SocialApp.objects.create(
                provider='strava',
                name='Strava',
                client_id=client_id,
                secret=secret,
            )
            # Collega al sito corrente (ID 1 di solito)
            try:
                site = Site.objects.get(id=1)
                app.sites.add(site)
            except Site.DoesNotExist:
                self.stdout.write("⚠️ Site ID 1 non trovato. Assicurati di configurare i Sites nell'admin.")

            self.stdout.write(self.style.SUCCESS(f"✅ SocialApp creata con ID: {app.id}"))
        else:
            self.stdout.write(f"✅ SocialApp Strava trovata (ID: {app.id}).")

        # 2. Ricollega i Token Orfani
        # Cerchiamo token Strava che non hanno un'app collegata (app_id IS NULL)
        tokens = SocialToken.objects.filter(account__provider='strava')
        count_fixed = 0
        
        for t in tokens:
            if not t.app:
                t.app = app
                t.save()
                self.stdout.write(f"   -> Token riparato per utente: {t.account.user.username}")
                count_fixed += 1
        
        if count_fixed > 0:
            self.stdout.write(self.style.SUCCESS(f"✅ Operazione completata! Riparati {count_fixed} token."))
        else:
            self.stdout.write("✅ Nessun token orfano trovato. Tutto ok.")