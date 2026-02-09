import time
import random
import os
import logging
import traceback
from django.core.management.base import BaseCommand
from atleti.models import ProfiloAtleta
from django.utils import timezone
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Aggiorna indici ITRA/UTMB usando Selenium con bypass cookie'

    def handle(self, *args, **options):
        logger.info("--- AVVIO TASK AGGIORNAMENTO INDICI ---")
        
        # Configurazione Chromium
        chrome_options = uc.ChromeOptions()
        chrome_options.binary_location = "/usr/bin/chromium" 
        
        chrome_options.add_argument('--headless=new') 
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage') 
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        
        try:
            # Usa undetected_chromedriver: scarica automaticamente il driver corretto per la versione di Chrome installata
            # version_main=None lascia che UC rilevi la versione dal binario del browser
            driver = uc.Chrome(options=chrome_options, browser_executable_path="/usr/bin/chromium", version_main=None)
            logger.info("✅ Driver UC avviato correttamente.")
        except Exception as e:
            logger.error(f"Errore critico avvio Driver (UC): {e}")
            return

        atleti = ProfiloAtleta.objects.all()

        for profilo in atleti:
            if not profilo.user.first_name or not profilo.user.last_name:
                continue
                
            nome_completo = f"{profilo.user.first_name} {profilo.user.last_name}"
            logger.info(f"Elaborazione per: {nome_completo}")
            
            # 1. LOGICA ITRA
            try:
                driver.get("https://www.google.com/")
                
                # --- BYPASS COOKIE (ID Universale + Fallback) ---
                try:
                    # ID L2AGLb clicca "Accetta tutto" indipendentemente dalla lingua
                    WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.ID, "L2AGLb"))).click()
                except:
                    try:
                        # Fallback testuale per sicurezza
                        WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Accetta') or contains(.,'Aceptar')]"))).click()
                    except: pass
                
                # Ricerca
                search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "q")))
                search_box.clear()
                for char in f"{nome_completo} itra":
                    search_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))
                search_box.send_keys(Keys.ENTER)
                
                time.sleep(random.uniform(2, 4))
                
                # Click sul risultato
                xpath_titolo = "//a[contains(@href, 'itra.run')]//h3"
                titolo_link = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath_titolo)))
                driver.execute_script("arguments[0].click();", titolo_link)

                # Estrazione Punteggio
                score_el = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.XPATH, '//*[@id="divProgress"]/div/span[1]')))
                punteggio = score_el.text.strip()
                if punteggio.isdigit():
                    profilo.indice_itra = int(punteggio)
                    logger.info(f"⭐ ITRA per {nome_completo}: {punteggio}")
                
            except Exception as e:
                logger.error(f"Errore ITRA {nome_completo}: {str(e)[:50]}")
                driver.save_screenshot(f"error_itra_{profilo.id}.png")

            # 2. LOGICA UTMB
            try:
                driver.get("https://www.google.com/")
                
                # Bypass Cookie
                try:
                    WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.ID, "L2AGLb"))).click()
                except: pass
                
                search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "q")))
                search_box.clear()
                for char in f"{nome_completo} utmb index":
                    search_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))
                search_box.send_keys(Keys.ENTER)
                
                time.sleep(random.uniform(2, 4))
                
                xpath_utmb = "//a[contains(@href, 'utmb.world')]//h3"
                titolo_utmb = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath_utmb)))
                driver.execute_script("arguments[0].click();", titolo_utmb)

                # Selettori Fallback UTMB
                wait_utmb = WebDriverWait(driver, 15)
                selettori = [
                    (By.CSS_SELECTOR, "h2[class*='performance_stat']"),
                    (By.XPATH, '//*[@id="reach-skip-nav"]//h2')
                ]
                for method, path in selettori:
                    try:
                        element = wait_utmb.until(EC.visibility_of_element_located((method, path)))
                        val = element.text.strip()
                        if val.isdigit():
                            profilo.indice_utmb = int(val)
                            logger.info(f"⭐ UTMB per {nome_completo}: {val}")
                            break
                    except: continue

            except Exception as e:
                logger.error(f"Errore UTMB {nome_completo}: {str(e)[:50]}")
                driver.save_screenshot(f"error_utmb_{profilo.id}.png")
            
            # Salvataggio e pausa "umana"
            profilo.data_aggiornamento_indici = timezone.now()
            profilo.save()
            time.sleep(random.uniform(4, 7))

        driver.quit()
        logger.info("--- TASK COMPLETATO ---")