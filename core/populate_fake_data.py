from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from atleti.models import ProfiloAtleta, Attivita
from atleti.utils import calcola_metrica_vo2max, stima_vo2max_atleta
import random
from datetime import timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = 'Popola il database con utenti e attività fittizie per test'

    def handle(self, *args, **kwargs):
        self.stdout.write("Inizio generazione dati fittizi...")

        # Dati per 3 profili tipo
        profili_fake = [
            {
                'username': 'giulia_elite', 'first_name': 'Giulia', 'last_name': 'Bianchi',
                'peso': 52.0, 'fc_riposo': 42, 'fc_max': 195,
                'itra': 750, 'utmb': 760, 'img': 'https://randomuser.me/api/portraits/women/44.jpg'
            },
            {
                'username': 'mario_amateur', 'first_name': 'Mario', 'last_name': 'Rossi',
                'peso': 75.0, 'fc_riposo': 55, 'fc_max': 185,
                'itra': 450, 'utmb': 460, 'img': 'https://randomuser.me/api/portraits/men/32.jpg'
            },
            {
                'username': 'luca_trail', 'first_name': 'Luca', 'last_name': 'Verdi',
                'peso': 68.0, 'fc_riposo': 48, 'fc_max': 190,
                'itra': 620, 'utmb': 630, 'img': 'https://randomuser.me/api/portraits/men/85.jpg'
            }
        ]

        for p_data in profili_fake:
            user, created = User.objects.get_or_create(username=p_data['username'])
            if created:
                user.set_password('testpass123')
                user.first_name = p_data['first_name']
                user.last_name = p_data['last_name']
                user.save()
                self.stdout.write(f"Creato utente: {user.username}")

            profilo, _ = ProfiloAtleta.objects.get_or_create(user=user)
            profilo.peso = p_data['peso']
            profilo.fc_riposo = p_data['fc_riposo']
            profilo.fc_max = p_data['fc_max']
            profilo.fc_massima_teorica = p_data['fc_max']
            profilo.immagine_profilo = p_data['img']
            profilo.indice_itra = p_data['itra']
            profilo.indice_utmb = p_data['utmb']
            profilo.save()

            # Generazione 40 attività per utente
            base_date = timezone.now()
            
            # Parametri base per la simulazione
            if 'elite' in user.username:
                base_pace = 240 # 4:00 min/km in secondi
                var_pace = 20
            elif 'trail' in user.username:
                base_pace = 300 # 5:00 min/km
                var_pace = 40
            else:
                base_pace = 330 # 5:30 min/km
                var_pace = 30

            for i in range(40):
                # Data a ritroso
                act_date = base_date - timedelta(days=i*2 + random.randint(0, 1))
                
                # Tipo attività
                is_trail = random.choice([True, False]) if 'trail' in user.username else random.random() < 0.2
                tipo = 'TrailRun' if is_trail else 'Run'
                
                # Distanza e Dislivello
                if tipo == 'TrailRun':
                    distanza = random.randint(10000, 35000)
                    dislivello = random.randint(400, 2000)
                    pace_seconds = base_pace + random.randint(60, 180) # Più lento su trail
                else:
                    distanza = random.randint(5000, 21000)
                    dislivello = random.randint(0, 200)
                    pace_seconds = base_pace + random.randint(-var_pace, var_pace)

                durata = int((distanza / 1000) * pace_seconds)
                
                # FC Media simulata (più alta se si va più forte, ma randomizzata)
                fc_media = int(profilo.fc_riposo + (profilo.fc_max - profilo.fc_riposo) * random.uniform(0.65, 0.85))
                
                # Passo medio stringa
                mins = pace_seconds // 60
                secs = pace_seconds % 60
                passo_str = f"{mins}:{secs:02d}"

                # Creazione Attività
                # Strava ID random univoco
                strava_id = 9000000000 + random.randint(1, 99999999)
                
                # Potenza simulata
                potenza = random.randint(200, 350) if random.random() > 0.3 else None

                att, created_act = Attivita.objects.get_or_create(
                    strava_activity_id=strava_id,
                    defaults={
                        'atleta': profilo,
                        'data': act_date,
                        'distanza': distanza,
                        'durata': durata,
                        'passo_medio': passo_str,
                        'fc_media': fc_media,
                        'fc_max_sessione': fc_media + random.randint(10, 25),
                        'dislivello': dislivello,
                        'tipo_attivita': tipo,
                        'potenza_media': potenza,
                        'cadenza_media': random.randint(160, 180)
                    }
                )
                
                if created_act:
                    # Calcolo VO2max usando la tua utility
                    att.vo2max_stimato = calcola_metrica_vo2max(att, profilo)
                    att.save()

            # Aggiorna statistiche profilo
            stima_vo2max_atleta(profilo)
            self.stdout.write(f"Completato profilo: {user.username}")

        self.stdout.write(self.style.SUCCESS('Database popolato con successo!'))