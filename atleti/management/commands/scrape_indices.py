from django.core.management.base import BaseCommand
from atleti.models import ProfiloAtleta
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import os
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Aggiorna indici ITRA/UTMB usando Selenium'

    def handle(self, *args, **options):
        logger.info("--- AVVIO TASK AGGIORNAMENTO INDICI ITRA/UTMB ---")
        
        # Configurazione Chrome Headless per Docker
        options = webdriver.ChromeOptions()
        options.binary_location = "/usr/bin/chromium" # Indica a Selenium di usare Chromium invece di Chrome
        
        # --- CONFIGURAZIONE STABILE PER DOCKER (Debian Bookworm) ---
        options.add_argument('--headless=new') # Usa la nuova modalità headless (più stabile)
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage') # Usa /tmp invece di /dev/shm
        options.add_argument('--disable-gpu')
        options.add_argument('--remote-debugging-port=9222') # Porta debug (aiuta la stabilità)
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        
        # User Agent (importante per non essere bloccati/crashare su Google)
        options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
        
        # Opzioni anti-bot base per Selenium standard
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        try:
            # Inizializzazione Driver
            # Usiamo il driver di sistema installato via apt
            if not os.path.exists("/usr/bin/chromium"):
                logger.warning("⚠️ ERRORE: /usr/bin/chromium non trovato!")
            if not os.path.exists("/usr/bin/chromedriver"):
                logger.warning("⚠️ ERRORE: /usr/bin/chromedriver non trovato!")
                
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=options)
            logger.info("✅ Driver Chromium avviato correttamente.")
        except Exception as e:
            logger.error(f"Errore critico avvio Chrome Driver: {e}")
            return

        atleti = ProfiloAtleta.objects.all()

        for profilo in atleti:
            if not profilo.user.first_name or not profilo.user.last_name:
                continue
                
            nome_completo = f"{profilo.user.first_name} {profilo.user.last_name}"
            logger.info(f"Elaborazione indici per: {nome_completo}")
            
            # LOGICA ITRA
            try:
                # 1. Navigazione Home Google (Simulazione Umana per evitare CAPTCHA)
                logger.info(f"DEBUG: Navigazione Home Google per ITRA...")
                driver.get("https://www.google.com/")
                
                # Gestione Cookie Google
                try:
                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Accetta')]"))).click()
                except Exception as e:
                    pass
                
                # Ricerca digitata
                search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "q")))
                for char in f"{nome_completo} itra":
                    search_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.2))
                search_box.send_keys(Keys.ENTER)
                
                time.sleep(random.uniform(2, 4))

                # 2. Identificazione e Click sul risultato ITRA
                xpath_titolo = "//a[contains(@href, 'itra.run')]//h3"
                titolo_da_cliccare = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_titolo))
                )
                titolo_da_cliccare.click()

                # 3. Estrazione Punteggio dalla pagina ITRA
                wait = WebDriverWait(driver, 10)
                score_element = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="divProgress"]/div/span[1]')))
                
                punteggio = score_element.text.strip()
                profilo.indice_itra = int(punteggio)
                self.stdout.write(self.style.SUCCESS(f"⭐ Punteggio ITRA trovato per {nome_completo}: {punteggio}"))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore scraping ITRA per {nome_completo}: {e}"))
                try:
                    driver.save_screenshot(f"debug_error_itra_{profilo.id}.png")
                    self.stdout.write(f"📸 Screenshot errore salvato: debug_error_itra_{profilo.id}.png")
                except Exception as s_e:
                    self.stdout.write(f"Impossibile salvare screenshot: {s_e}")

            # LOGICA UTMB
            try:
                # 1. Navigazione Home Google (Simulazione Umana)
                self.stdout.write(f"DEBUG: Navigazione Home Google per UTMB...")
                driver.get("https://www.google.com/")
                
                # Gestione Cookie Google
                try:
                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Accetta')]"))).click()
                except:
                    pass
                
                # Ricerca digitata
                search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "q")))
                for char in f"{nome_completo} utmb index":
                    search_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.2))
                search_box.send_keys(Keys.ENTER)
                
                time.sleep(random.uniform(2, 4))

                # 2. Trova e clicca il titolo UTMB
                xpath_titolo = "//a[contains(@href, 'utmb.world')]//h3"
                titolo = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath_titolo)))
                titolo.click()

                # 3. Estrazione Punteggio con Logica Fallback
                wait = WebDriverWait(driver, 15)
                selettori = [
                    (By.CSS_SELECTOR, "h2[class*='performance_stat']"), # Cerca la classe generica
                    (By.XPATH, '//*[@id="reach-skip-nav"]/div/div[3]/div/div[2]/div/div[1]/h2'), # Layout 1
                    (By.XPATH, '//*[@id="reach-skip-nav"]/div/div[2]/div/div[2]/div/div[1]/h2')  # Layout 2
                ]

                for bypass_method, path in selettori:
                    try:
                        element = wait.until(EC.visibility_of_element_located((bypass_method, path)))
                        punteggio = element.text.strip()
                        if punteggio.isdigit():
                            profilo.indice_utmb = int(punteggio)
                            logger.info(f"⭐ UTMB Index trovato per {nome_completo}: {punteggio}")
                            break
                    except:
                        continue

            except Exception as e:
                logger.error(f"Errore scraping UTMB per {nome_completo}: {e}")
                try:
                    driver.save_screenshot(f"debug_error_utmb_{profilo.id}.png")
                    logger.info(f"📸 Screenshot errore salvato: debug_error_utmb_{profilo.id}.png")
                except Exception as s_e:
                    logger.error(f"Impossibile salvare screenshot: {s_e}")
            
            profilo.data_aggiornamento_indici = timezone.now()
            profilo.save()

        driver.quit()
        logger.info("--- TASK AGGIORNAMENTO COMPLETATO ---")