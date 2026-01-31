from django.core.management import call_command
from django.db import close_old_connections
import logging
import undetected_chromedriver as uc
import time
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.utils import timezone
from .models import ProfiloAtleta, Attivita
from allauth.socialaccount.models import SocialToken
from .utils import refresh_strava_token, processa_attivita_strava, stima_vo2max_atleta
import requests

# Configura il logger per tracciare l'esecuzione
logger = logging.getLogger(__name__)

def task_ricalcolo_vam():
    """
    Task pianificato per ricalcolare la VAM Selettiva.
    """
    logger.info("SCHEDULER: Avvio ricalcolo VAM Selettiva...")
    # Chiama il comando esistente. --force è opzionale, qui non lo mettiamo per risparmiare API
    call_command('recalculate_vam')
    logger.info("SCHEDULER: Ricalcolo VAM completato.")

def task_ricalcolo_statistiche():
    """
    Task pianificato per aggiornare le statistiche (VO2max, Trend, ecc).
    """
    logger.info("SCHEDULER: Avvio ricalcolo Statistiche Generali...")
    call_command('recalculate_stats')
    logger.info("SCHEDULER: Ricalcolo Statistiche completato.")

def task_scrape_itra_utmb():
    """
    Task pianificato per scaricare i dati ITRA/UTMB con Selenium.
    """
    logger.info("SCHEDULER: Avvio scraping dati ITRA/UTMB...")
    call_command('scrape_indices')
    logger.info("SCHEDULER: Scraping ITRA/UTMB completato.")

def task_heartbeat():
    """Task di sistema per tenere sveglio lo scheduler (polling DB)"""
    # Chiudiamo le connessioni vecchie per evitare che il task si blocchi su connessioni stale
    close_old_connections()
    
    from .models import TaskSettings
    from django_apscheduler.models import DjangoJobExecution, DjangoJob
    
    # Mappa task_id -> (tipo, target)
    # 'cmd': Management Command Django
    # 'func': Funzione Python definita in questo file
    task_map = {
        'ricalcolo_vam_notturno': ('cmd', 'recalculate_vam'),
        'ricalcolo_stats_notturno': ('cmd', 'recalculate_stats'),
        'scrape_itra_utmb_settimanale': ('cmd', 'scrape_indices'),
        'pulizia_log_settimanale': ('cmd', 'clean_scheduler_logs'),
        'sync_strava_periodico': ('func', 'task_sync_strava'), # Aggiunto supporto Strava
    }

    # Cerca task con trigger manuale attivo
    configs = TaskSettings.objects.filter(manual_trigger=True)
    
    for cfg in configs:
        logger.info(f"SCHEDULER: Rilevato trigger manuale per {cfg.task_id}")
        
        task_info = task_map.get(cfg.task_id)
        if task_info:
            type_, target_name = task_info
            start_time = timezone.now()
            status = "Executed"
            exception = ""
            
            try:
                if type_ == 'cmd':
                    logger.info(f"SCHEDULER: Esecuzione comando '{target_name}'...")
                    call_command(target_name)
                elif type_ == 'func':
                    # Recupera la funzione dinamicamente dal modulo corrente
                    func = globals().get(target_name)
                    if func:
                        logger.info(f"SCHEDULER: Esecuzione funzione '{target_name}'...")
                        func()
                    else:
                        raise ValueError(f"Funzione {target_name} non trovata.")

                logger.info(f"SCHEDULER: Esecuzione manuale di {cfg.task_id} completata.")
            except Exception as e:
                logger.error(f"SCHEDULER: Errore esecuzione manuale {cfg.task_id}: {e}")
                status = "Error"
                exception = str(e)
            finally:
                # CRUCIALE: Resettiamo il flag SEMPRE, anche in caso di errore
                # Questo sblocca il bottone nell'interfaccia web
                cfg.manual_trigger = False
                cfg.save()
                logger.info(f"SCHEDULER: Reset flag manuale per {cfg.task_id}")

            # Registra l'esecuzione manuale nello storico
            try: 
                duration = (timezone.now() - start_time).total_seconds()
                job = DjangoJob.objects.filter(id=cfg.task_id).first()
                if job:
                    DjangoJobExecution.objects.create(
                        job=job,
                        status=status,
                        run_time=start_time,
                        duration=duration,
                        finished=timezone.now().timestamp(),
                        exception=exception
                    )
            except Exception as e_db:
                logger.error(f"SCHEDULER: Errore salvataggio log DB: {e_db}")

def task_sync_strava():
    """
    Task periodico per sincronizzare le attività da Strava per tutti gli utenti.
    Gestisce automaticamente il refresh del token.
    """
    # Chiudiamo le connessioni vecchie prima di iniziare operazioni lunghe col DB
    close_old_connections()
    
    logger.info("SCHEDULER: Avvio sincronizzazione Strava automatica...")
    
    tokens = SocialToken.objects.filter(account__provider='strava')
    
    for token_obj in tokens:
        close_old_connections() # Rinnova connessione DB per ogni utente (fondamentale per task lunghi)
        user = token_obj.account.user
        logger.info(f"--- Sync Strava per: {user.username} ---")
        
        # 1. Refresh Token (se necessario)
        # Usiamo un buffer ampio (4 ore) per mantenere il token vivo tra un'esecuzione e l'altra
        access_token = refresh_strava_token(token_obj, buffer_minutes=240)
        if not access_token:
            logger.error(f"Impossibile rinnovare token per {user.username}. Salto.")
            continue
            
        # 2. Scarica Attività (Solo ultime 10 per risparmiare API nel task automatico)
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'page': 1, 'per_page': 10} 
        
        try:
            response = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params, timeout=15)
            
            if response.status_code == 200:
                activities = response.json()
                profilo, _ = ProfiloAtleta.objects.get_or_create(user=user)
                
                count_new = 0
                for act in activities:
                    if act['type'] not in ['Run', 'TrailRun', 'Hike']:
                        continue
                    
                    # Usiamo la utility centralizzata
                    _, created = processa_attivita_strava(act, profilo, access_token)
                    if created:
                        count_new += 1
                
                if count_new > 0:
                    stima_vo2max_atleta(profilo)
                    logger.info(f"Importate {count_new} nuove attività.")
                else:
                    logger.info("Nessuna nuova attività.")
                
                # Aggiorniamo timestamp sync
                profilo.data_ultima_sincronizzazione = timezone.now()
                profilo.save()
                    
            elif response.status_code == 429:
                logger.warning("Rate Limit Strava raggiunto. Interrompo sync globale.")
                break 
            else:
                logger.error(f"Errore API Strava: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Errore durante sync per {user.username}: {e}")
            
        time.sleep(30) # Pausa etica tra utenti (30s per evitare Rate Limits)
        
    logger.info("SCHEDULER: Sincronizzazione Strava completata.")