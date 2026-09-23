import json
import urllib.request
import urllib.error
import os
import time
from django.core.management.base import BaseCommand
from squadra_calcio.models import Giocatore, Presenza, Risultato, Categoria, CacheApi # Assicurati che 'squadra_calcio' sia il nome corretto della tua app

class Command(BaseCommand):
    help = 'Chiama Gemini AI in background e salva il report in cache.'

    def handle(self, *args, **kwargs):
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY_2", "")
        if not GEMINI_API_KEY:
            self.stdout.write(self.style.ERROR("ERRORE: Chiave API Gemini mancante nelle variabili d'ambiente."))
            return

        categorie = [cat[0] for cat in Categoria.choices]

        for categoria in categorie:
            self.stdout.write(f"Avvio analisi AI per {categoria}...")
            
            try:
                # 1. RICOSTRUISCE I DATI
                anno_inizio = str(categoria)[:4]
                giocatori = Giocatore.objects.filter(categoria__startswith=anno_inizio, attivo=True)
                
                classifica = []
                for g in giocatori:
                    pres = Presenza.objects.filter(giocatore=g)
                    presenti = pres.filter(presente=True).count()
                    giustificate = pres.filter(presente=False, situazione='Assenza Giustificata').count()
                    ingiustificate = pres.filter(presente=False).exclude(situazione='Assenza Giustificata').count()
                    classifica.append({
                        'nome': g.nome_cognome,
                        'presenze': presenti,
                        'giustificate': giustificate,
                        'ingiustificate': ingiustificate
                    })

                cat_trattino = str(categoria).replace('/', '-')
                risultati_db = Risultato.objects.filter(categoria__in=[categoria, cat_trattino]).order_by('-data_partita')[:5]
                risultati = [{'avversario': r.avversario, 'gol_fatti': r.gol_fatti, 'gol_subiti': r.gol_subiti} for r in risultati_db]

                # 2. PREPARA IL PROMPT PER GEMINI
                prompt = f"""
                Sei 'Mastra-AI', un assistente per un allenatore di calcio giovanile in Italia (categoria {categoria}).
                Ricorda che l'obiettivo primario di questa età è la CRESCITA dei ragazzi, la coesione del gruppo e il divertimento, non solo la vittoria. Tuttavia i buoni risultati aiutano il morale.

                Analizza questi dati della squadra:
                1. Dati Presenze: {json.dumps(classifica)}
                2. Ultimi Risultati Partite: {json.dumps(risultati)}

                Per favore genera un breve report diviso in:
                - VALUTAZIONE PARTECIPAZIONE: Analizza se i ragazzi vengono agli allenamenti. Chi c'è di più, chi sta mollando (troppe assenze).
                - ANALISI RISULTATI: Come stanno andando le partite. Segnamo? Subiamo troppo?
                - CONSIGLI PRATICI: Dammi 2 o 3 consigli pratici (esercizi, approccio psicologico o tattico di base) per migliorare le debolezze che vedi nei numeri, tenendo a mente la loro età. Sii conciso e diretto.
                """

                # FIX APPLICATO QUI: gemini-1.5-flash
                # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})

                # 3. CHIAMA GEMINI
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    testo_ai = res_data['candidates'][0]['content']['parts'][0]['text']

                    # 4. SALVA IN CACHE
                    CacheApi.objects.update_or_create(
                        endpoint='analisi_ia',
                        categoria=categoria,
                        defaults={'payload_json': testo_ai} 
                    )
                    self.stdout.write(self.style.SUCCESS(f"✅ Analisi AI aggiornata per {categoria}"))

            except urllib.error.HTTPError as e:
                errore_google = e.read().decode('utf-8')
                self.stdout.write(self.style.ERROR(f"❌ Errore Google per {categoria}: {errore_google}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Errore generico per {categoria}: {str(e)}"))
            
            # FIX APPLICATO QUI: Pausa di 2 secondi tra una categoria e l'altra per non saturare l'API
            time.sleep(2)