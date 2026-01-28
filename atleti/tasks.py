from django.core.management import call_command
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
    from .models import TaskSettings
    from django_apscheduler.models import DjangoJobExecution, DjangoJob
    
    # Mappa task_id -> comando management
    task_map = {
        'ricalcolo_vam_notturno': 'recalculate_vam',
        'ricalcolo_stats_notturno': 'recalculate_stats',
        'scrape_itra_utmb_settimanale': 'scrape_indices',
        'pulizia_log_settimanale': 'clean_scheduler_logs',
    }

    # Cerca task con trigger manuale attivo
    configs = TaskSettings.objects.filter(manual_trigger=True)
    
    for cfg in configs:
        logger.info(f"SCHEDULER: Rilevato trigger manuale per {cfg.task_id}")
        cmd = task_map.get(cfg.task_id)
        if cmd:
            start_time = timezone.now()
            status = "Executed"
            exception = ""
            try:
                call_command(cmd)
                logger.info(f"SCHEDULER: Esecuzione manuale di {cfg.task_id} completata.")
            except Exception as e:
                logger.error(f"SCHEDULER: Errore esecuzione manuale {cfg.task_id}: {e}")
                status = "Error"
                exception = str(e)
            
            # Registra l'esecuzione manuale nello storico (DjangoJobExecution)
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
        
        # Resetta il flag
        cfg.manual_trigger = False
        cfg.save()

def task_sync_strava():
    """
    Task periodico per sincronizzare le attività da Strava per tutti gli utenti.
    Gestisce automaticamente il refresh del token.
    """
    logger.info("SCHEDULER: Avvio sincronizzazione Strava automatica...")
    
    tokens = SocialToken.objects.filter(account__provider='strava')
    
    for token_obj in tokens:
        user = token_obj.account.user
        logger.info(f"--- Sync Strava per: {user.username} ---")
        
        # 1. Refresh Token (se necessario)
        access_token = refresh_strava_token(token_obj)
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