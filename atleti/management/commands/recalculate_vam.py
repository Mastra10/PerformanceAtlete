from django.core.management.base import BaseCommand
from atleti.models import ProfiloAtleta, Attivita
from atleti.utils import calcola_vam_selettiva
from allauth.socialaccount.models import SocialToken
import time
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Ricalcola la VAM Selettiva per le attività TrailRun esistenti scaricando gli streams da Strava'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forza il ricalcolo anche se la VAM è già presente',
        )

    def handle(self, *args, **options):
        logger.info("Inizio ricalcolo VAM Selettiva...")
        force = options['force']
        
        atleti = ProfiloAtleta.objects.all()
        
        for profilo in atleti:
            logger.info(f"--- Elaborazione atleta: {profilo.user.username} ---")
            
            # Recupera il token Strava
            token_obj = SocialToken.objects.filter(account__user=profilo.user, account__provider='strava').first()
            
            if not token_obj:
                logger.warning(f"⚠️ Token Strava non trovato per {profilo.user.username}. Salto.")
                continue
            
            # Filtra solo TrailRun con dislivello > 150m
            qs = Attivita.objects.filter(
                atleta=profilo, 
                tipo_attivita='TrailRun', 
                dislivello__gt=150
            ).order_by('-data')
            
            count_ok = 0
            count_skip = 0
            
            for act in qs:
                # Se abbiamo già il dato e non forziamo, saltiamo per risparmiare API
                if act.vam_selettiva and act.vam_selettiva > 0 and not force:
                    count_skip += 1
                    continue

                logger.info(f"Scaricamento streams per attività {act.strava_activity_id} ({act.data.date()})...")
                
                vam = calcola_vam_selettiva(act.strava_activity_id, token_obj.token)
                
                if vam is not None:
                    act.vam_selettiva = vam
                    act.save()
                    logger.info(f" OK -> VAM: {vam} m/h")
                    count_ok += 1
                    # Rate Limit Friendly: Strava permette 100 richieste ogni 15 min.
                    # 1.5s di pausa = max 40 richieste al minuto, sicuro.
                    time.sleep(1.5) 
                else:
                    logger.error(" ERRORE o Rate Limit")
            
            logger.info(f"Finito {profilo.user.username}: {count_ok} aggiornati, {count_skip} saltati.")

        logger.info('Task completato.')