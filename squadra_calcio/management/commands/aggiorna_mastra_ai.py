import json
import urllib.request
import urllib.error
import os
import time
from django.core.management.base import BaseCommand
from squadra.models import Giocatore, Presenza, Risultato, Categoria, CacheApi

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
                # 1. RICOSTRUISCE I DATI (FILTRANDO I DIRIGENTI E I CALENDARI FUTURI)
                anno_inizio = str(categoria)[:4]
                
                # --- FILTRO 1: ESTRAIAMO SOLO I VERI GIOCATORI DAL DB ---
                giocatori = Giocatore.objects.filter(categoria__startswith=anno_inizio, ruolo='Giocatore', attivo=True)
                
                classifica = []
                for g in giocatori:
                    pres = Presenza.objects.filter(giocatore=g)
                    totale = pres.filter(evento__tipo='Allenamento').count()
                    presenti = pres.filter(evento__tipo='Allenamento', presente=True).count()
                    giustificate = pres.filter(evento__tipo='Allenamento', presente=False, situazione='Assenza Giustificata').count()
                    ingiustificate = pres.filter(evento__tipo='Allenamento', presente=False).exclude(situazione='Assenza Giustificata').count()
                    perc = round((presenti / totale) * 100, 1) if totale > 0 else 0.0
                    
                    classifica.append({
                        'nome': g.nome_cognome,
                        'presenze': presenti,
                        'totale': totale,
                        'percentuale': str(perc),
                        'giustificate': giustificate,
                        'ingiustificate': ingiustificate
                    })

                # --- FILTRO 2: PRENDIAMO SOLO LE PARTITE CONVALIDATE (GIA' GIOCATE) ---
                cat_trattino = str(categoria).replace('/', '-')
                risultati_db = Risultato.objects.filter(
                    categoria__in=[categoria, cat_trattino], 
                    convalidata=True # FILTRO CHIAVE
                ).order_by('-data_partita')[:5]
                
                risultati = [{'avversario': r.avversario, 'gol_fatti': r.gol_fatti, 'gol_subiti': r.gol_subiti} for r in risultati_db]

                # 2. PREPARA IL PROMPT PER GEMINI
                prompt = f"""
                Sei 'Mastra-AI', il mister in seconda per la squadra {categoria} del Fraore Lab.
                Analizza questi dati aggiornati:

                📊 PRESENZE AGLI ALLENAMENTI:
                """
                if not classifica:
                    prompt += "Nessun dato sulle presenze ancora inserito.\n"
                else:
                    for c in classifica:
                        prompt += f"- {c['nome']}: {c['presenze']} su {c['totale']} ({c['percentuale']}%) - Giust: {c['giustificate']}, Ingiust: {c['ingiustificate']}\n"

                prompt += "\n⚽ RISULTATI PARTITE (Solo giocate e convalidate):\n"
                if not risultati:
                    prompt += "Nessuna partita convalidata al momento.\n"
                else:
                    for r in risultati:
                        gol_f = r['gol_fatti']
                        gol_s = r['gol_subiti']
                        esito = "Vittoria" if gol_f > gol_s else "Sconfitta" if gol_f < gol_s else "Pareggio"
                        prompt += f"- vs {r['avversario']} | Risultato: {gol_f}-{gol_s} ({esito})\n"

                prompt += """
                Scrivi un report tattico e motivazionale (massimo 15-20 righe) usando la formattazione Markdown e le emoji. Strutturalo sempre in questo modo:
                1. **Analisi Presenze:** Loda i più presenti e segnala, con molto tatto e senza accusare, le situazioni critiche o chi ha assenze ingiustificate.
                2. **Analisi Risultati:** Fai una disamina oggettiva di come stanno andando le partite basandoti sull'andamento e i gol fatti/subiti.
                3. **Consiglio Pratico:** Un suggerimento tecnico/tattico su cosa allenare questa settimana.
                """

                # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})

                # 3. CHIAMA GEMINI E SALVA IN CACHE
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    testo_ai = res_data['candidates'][0]['content']['parts'][0]['text']

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
                import traceback
                traceback.print_exc()
                self.stdout.write(self.style.ERROR(f"❌ Errore generico per {categoria}: {str(e)}"))
            
            time.sleep(2)