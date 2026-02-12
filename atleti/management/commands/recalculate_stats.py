import logging
from django.core.management.base import BaseCommand
from atleti.models import ProfiloAtleta, Attivita
from atleti.utils import stima_vo2max_atleta, calcola_metrica_vo2max
from django.utils import timezone

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Ricalcola le statistiche (VO2max Strada/Stima) per tutti gli atleti'

    def handle(self, *args, **kwargs):
        logger.info("Inizio ricalcolo statistiche...")
        
        atleti = ProfiloAtleta.objects.all()
        count = 0
        
        for profilo in atleti:
            # logger.info(f"Elaborazione: {profilo.user.username}...")
            
            # 1. Ricalcola VO2max per ogni singola attività (se necessario)
            # Utile se abbiamo cambiato la formula in utils.py
            # Ricalcoliamo tutto lo storico per coerenza nei grafici dopo cambio algoritmo
            attivita = Attivita.objects.filter(atleta=profilo).order_by('-data')
            
            updated_activities = 0
            for act in attivita:
                if act.distanza > 0 and act.durata > 0:
                    # Ricalcoliamo sempre per essere sicuri di avere il dato aggiornato con l'ultima formula
                    nuovo_vo2 = calcola_metrica_vo2max(act, profilo)
                    # Aggiorniamo anche se è None (es. attività ora esclusa per passo lento)
                    if act.vo2max_stimato != nuovo_vo2:
                        act.vo2max_stimato = nuovo_vo2
                        act.save()
                        updated_activities += 1

            # 2. Aggiorna i campi aggregati del profilo (incluso vo2max_strada)
            profilo.data_ultimo_ricalcolo_statistiche = timezone.now()
            stima_vo2max_atleta(profilo)
            count += 1
            
            if updated_activities > 0:
                logger.info(f"Aggiornato {profilo.user.username}: {updated_activities} attività ricalcolate.")

        logger.info(f'Ricalcolo completato! Aggiornati {count} profili.')