from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialToken
from atleti.models import ProfiloAtleta, Scarpa
from atleti.utils import refresh_strava_token, normalizza_scarpa
import requests

class Command(BaseCommand):
    help = 'Scarica e aggiorna le scarpe per tutti gli utenti Strava collegati'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Avvio aggiornamento massivo scarpe..."))
        
        tokens = SocialToken.objects.filter(account__provider='strava')
        count_users = 0
        
        for token_obj in tokens:
            user = token_obj.account.user
            self.stdout.write(f"Elaborazione utente: {user.username}...")
            
            token = refresh_strava_token(token_obj)
            if not token:
                self.stdout.write(self.style.ERROR(f"  -> Token scaduto o non valido."))
                continue
                
            try:
                headers = {'Authorization': f'Bearer {token}'}
                res = requests.get("https://www.strava.com/api/v3/athlete", headers=headers, timeout=10)
                
                if res.status_code == 200:
                    data = res.json()
                    profilo, _ = ProfiloAtleta.objects.get_or_create(user=user)
                    
                    shoes = data.get('shoes', [])
                    ids = []
                    for s in shoes:
                        ids.append(s['id'])
                        brand, model = normalizza_scarpa(s['name'])
                        Scarpa.objects.update_or_create(
                            strava_id=s['id'],
                            defaults={
                                'atleta': profilo, 'nome': s['name'], 'distanza': s['distance'],
                                'primary': s['primary'], 'brand': brand, 'modello_normalizzato': model,
                                'retired': False
                            }
                        )
                    # Segna come dismesse quelle non più presenti
                    Scarpa.objects.filter(atleta=profilo).exclude(strava_id__in=ids).update(retired=True)
                    self.stdout.write(self.style.SUCCESS(f"  -> Aggiornate {len(shoes)} scarpe."))
                    count_users += 1
                else:
                    self.stdout.write(self.style.ERROR(f"  -> Errore API Strava: {res.status_code}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  -> Eccezione: {e}"))
        
        self.stdout.write(self.style.SUCCESS(f"Operazione completata su {count_users} utenti."))