from django.apps import AppConfig
import os
import logging

logger = logging.getLogger(__name__)


class AtletiConfig(AppConfig):
    name = 'atleti'

    def ready(self):
        # Lo scheduler ora è gestito come servizio separato tramite il comando 'run_scheduler'
        
        # --- MONKEY PATCH ALLAUTH STRAVA ---
        # Fix per errore "KeyError: 'id'" che capita randomicamente quando Strava
        # non restituisce l'oggetto atleta nel token response (es. errori API o scope parziali).
        # Invece di crashare con 500, solleviamo un errore gestito e logghiamo il payload.
        try:
            from allauth.socialaccount.providers.strava.provider import StravaProvider
            from allauth.socialaccount.providers.oauth2.client import OAuth2Error
            
            original_extract_uid = StravaProvider.extract_uid
            
            def safe_extract_uid(self, data):
                if not isinstance(data, dict):
                    logger.error(f"STRAVA LOGIN ERROR: Risposta non è un dizionario. Tipo: {type(data)} - Dati: {data}")
                    raise OAuth2Error("Risposta invalida da Strava (Formato errato).")
                    
                if 'id' not in data:
                    # Logghiamo il payload per capire cosa sta succedendo (es. Rate Limit, Errore Server Strava)
                    logger.error(f"STRAVA LOGIN ERROR: 'id' mancante. Payload ricevuto: {data}")
                    
                    if 'message' in data:
                        raise OAuth2Error(f"Errore Strava: {data['message']}")
                        
                    raise OAuth2Error("Risposta invalida da Strava: ID atleta mancante.")
                    
                return original_extract_uid(self, data)
                
            StravaProvider.extract_uid = safe_extract_uid
            
        except ImportError as e:
            logger.warning(f"Impossibile applicare patch Strava Allauth: {e}")
        except Exception as e:
            logger.error(f"Errore applicazione patch Strava: {e}")
