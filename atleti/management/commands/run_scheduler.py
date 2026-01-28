import logging
from django.conf import settings
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore, register_events
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util
from atleti.tasks import task_ricalcolo_vam, task_ricalcolo_statistiche, task_scrape_itra_utmb, task_heartbeat, task_sync_strava
from atleti.models import TaskSettings

# Configurazione Logging con Data e Ora per Docker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

@util.close_old_connections
def delete_old_job_executions(max_age=604_800):
    """Cancella i log di esecuzione più vecchi di 7 giorni (604800 sec)"""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)

class Command(BaseCommand):
    help = "Avvia lo schedulatore di task (APScheduler)"

    def handle(self, *args, **options):
        # Configurazione File Log per la Dashboard
        log_file = '/code/scheduler.log'
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'))
        
        # --- FILTRO ANTI-SPAM ---
        class HeartbeatFilter(logging.Filter):
            def filter(self, record):
                msg = record.getMessage()
                if "task_heartbeat" in msg:
                    # Nascondiamo solo i log di routine (INFO), ma mostriamo gli ERRORI
                    if "Running job" in msg or "executed successfully" in msg:
                        return False
                return True

        f = HeartbeatFilter()
        file_handler.addFilter(f)

        # Applichiamo il filtro a TUTTI i handler del root logger (inclusa la console di Docker)
        root_logger = logging.getLogger('')
        for h in root_logger.handlers:
            h.addFilter(f)
        root_logger.addHandler(file_handler)
        
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")
        
        # REGISTRAZIONE EVENTI: Fondamentale per salvare i log nel DB e vederli nel sito!
        register_events(scheduler)

        # --- DEFINIZIONE DEI JOB ---
        # Funzione helper per caricare o creare la config
        def schedule_task(task_func, task_id, default_hour, default_minute, default_day='*'):
            try:
                cfg, created = TaskSettings.objects.get_or_create(
                    task_id=task_id,
                    defaults={
                        'hour': str(default_hour),
                        'minute': str(default_minute),
                        'day_of_week': str(default_day),
                        'active': True
                    }
                )
                
                if cfg.active:
                    scheduler.add_job(
                        task_func,
                        trigger=CronTrigger(hour=cfg.hour, minute=cfg.minute, day_of_week=cfg.day_of_week),
                        id=task_id,
                        max_instances=1,
                        replace_existing=True,
                        misfire_grace_time=None,  # Esegui anche se in ritardo (fondamentale per task manuali)
                        coalesce=True,            # Se si accumulano più esecuzioni, fanne una sola
                    )
                    logger.info(f"Job aggiunto: '{task_id}' (Ore: {cfg.hour}:{cfg.minute}, Giorno: {cfg.day_of_week})")
                else:
                    logger.info(f"Job disabilitato da config: '{task_id}'")
                    
            except Exception as e:
                logger.error(f"Errore caricamento config per {task_id}: {e}")
                # Fallback sui default se il DB non è raggiungibile o migrato
                scheduler.add_job(
                    task_func,
                    trigger=CronTrigger(hour=default_hour, minute=default_minute, day_of_week=default_day),
                    id=task_id,
                    max_instances=1,
                    replace_existing=True,
                    misfire_grace_time=None,
                    coalesce=True,
                )
                logger.warning(f"Usata configurazione di default per '{task_id}'")

        # 1. Ricalcolo VAM Selettiva (Ogni notte alle 03:00)
        schedule_task(
            task_ricalcolo_vam,
            "ricalcolo_vam_notturno",
            default_hour=3, default_minute=0
        )

        # 2. Ricalcolo Statistiche Generali (Ogni notte alle 04:00)
        schedule_task(
            task_ricalcolo_statistiche,
            "ricalcolo_stats_notturno",
            default_hour=4, default_minute=0
        )

        # 3. Scraping ITRA/UTMB (Ogni Lunedì alle 05:00)
        schedule_task(
            task_scrape_itra_utmb,
            "scrape_itra_utmb_settimanale",
            default_hour=5, default_minute=0, default_day='mon'
        )

        # 4. Pulizia Log (Ogni Lunedì alle 00:00)
        schedule_task(
            delete_old_job_executions,
            "pulizia_log_settimanale",
            default_hour=0, default_minute=0, default_day='mon'
        )
        
        # 5. Sync Strava Automatico (Ogni notte alle 02:30)
        schedule_task(
            task_sync_strava,
            "sync_strava_periodico",
            default_hour=2, default_minute=30
        )
        
        # 5. SYSTEM HEARTBEAT (Ogni 10 secondi)
        # Serve a svegliare lo scheduler per fargli leggere i task manuali dal DB
        scheduler.add_job(
            task_heartbeat,
            trigger=CronTrigger(second='*/10'), # Ogni 10 secondi
            id="system_heartbeat",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=None,
            coalesce=True,
        )

        try:
            logger.info("Avvio dello schedulatore...")
            scheduler.start()
        except KeyboardInterrupt:
            logger.info("Arresto schedulatore in corso...")
            scheduler.shutdown()
            logger.info("Schedulatore arrestato con successo.")