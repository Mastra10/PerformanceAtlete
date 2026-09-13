import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Giocatore, Evento, Presenza , LogModifica , Risultato, AllarmeAck
import traceback
import urllib.request
import urllib.error
import json
import os

def api_get_giocatori(request, categoria):
    """
    Ritorna la lista dei giocatori attivi per una specifica categoria.
    Esempio di url: /squadra/api/giocatori/2013/
    """
    # Fix temporaneo se passi solo l'anno iniziale (es. "2013" diventa "2013/2014")
    if len(categoria) == 4:
        categoria = f"{categoria}/{str(int(categoria)+1)}"
        
    giocatori = Giocatore.objects.filter(categoria=categoria, attivo=True)
    
    dati = []
    for g in giocatori:
        dati.append({
            "id": g.id,
            "nome": g.nome_cognome,
            "categoria": g.categoria,
            "telefono_giocatore": g.telefono_giocatore,
            "telefono_genitore": g.telefono_genitore,
            'tessera_csi': g.tessera_csi,
            'tessera_figc': g.tessera_figc,
            'scadenza_certificato': g.scadenza_certificato.strftime("%d/%m/%Y") if g.scadenza_certificato else None,
            'scadenza_visita_medica': g.scadenza_visita_medica.strftime("%d/%m/%Y") if g.scadenza_visita_medica else None,
            'scadenza_carta_identita': g.scadenza_carta_identita.strftime("%d/%m/%Y") if g.scadenza_carta_identita else None,
            "modulo_golee_compilato": g.modulo_golee_compilato,
            "note_mediche": g.note_mediche, 


            # La proprietà calcolata nel modello
            "certificato_scaduto": g.certificato_scaduto 
        })
        
    return JsonResponse({"status": "success", "giocatori": dati})


@csrf_exempt
def api_salva_presenza(request):
    """
    Riceve un JSON dall'app e salva o aggiorna la presenza per un evento.
    Traccia anche il nome del dispositivo/dirigente che fa l'operazione.
    """
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            giocatore_id = body.get('giocatore_id')
            evento_id = body.get('evento_id')
            presente = body.get('presente', False)
            situazione = body.get('situazione', '')
            firma_dispositivo = body.get('firma_dispositivo', 'Sconosciuto')

            # update_or_create: se esiste già la aggiorna, altrimenti la crea
            presenza, creata = Presenza.objects.update_or_create(
                giocatore_id=giocatore_id,
                evento_id=evento_id,
                defaults={
                    'presente': presente,
                    'situazione': situazione,
                    'firma_dispositivo': firma_dispositivo
                }
            )
            return JsonResponse({
                "status": "success", 
                "presenza_id": presenza.id, 
                "creata": creata,
                "inserito_da": firma_dispositivo
            })
            
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
            
    return JsonResponse({"status": "error", "message": "Metodo non consentito. Usa POST"}, status=405)


@csrf_exempt
def api_crea_giocatore(request):
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            def clean_date(d):
                return d if d and str(d).strip() != '' else None
            
            Giocatore.objects.create(
                nome_cognome=body.get('nome_cognome'),
                categoria=body.get('categoria'),
                telefono_giocatore=body.get('telefono_giocatore'),
                telefono_genitore=body.get('telefono_genitore'),
                tessera_csi=body.get('tessera_csi'),
                tessera_figc=body.get('tessera_figc'),
                scadenza_visita_medica=clean_date(body.get('scadenza_visita_medica')),
                scadenza_carta_identita=clean_date(body.get('scadenza_carta_identita')),
                data_nascita=clean_date(body.get('data_nascita')),
                ruolo=body.get('ruolo', 'Giocatore')
            )
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

            
    


def api_get_eventi(request, categoria):
    """
    Ritorna gli ultimi eventi per una categoria. 
    Serve all'app per popolare la tendina di selezione (es. scegli l'allenamento di oggi).
    """
    if request.method == "GET":
        if len(categoria) == 4:
            categoria = f"{categoria}/{str(int(categoria)+1)}"
            
        # Prendiamo gli ultimi 20 eventi (Allenamenti o Partite) per non sovraccaricare l'app
        eventi = Evento.objects.filter(categoria_squadra=categoria).order_by('-data')[:20]
        
        dati = []
        for e in eventi:
            dati.append({
                "id": e.id,
                "tipo": e.tipo,
                "data": e.data.strftime("%d/%m/%Y"),
                "descrizione": str(e) # Usa il __str__ definito nel tuo models.py
            })
            
        return JsonResponse({"status": "success", "eventi": dati})

@csrf_exempt
def api_get_giocatori(request, categoria):
    try:
        anno_inizio = str(categoria)[:4]
        # Adesso estraiamo esplicitamente tutti i campi, comprese le date!
        giocatori = Giocatore.objects.filter(categoria__startswith=anno_inizio).values(
            'id', 'nome_cognome', 'categoria', 'telefono_giocatore', 'telefono_genitore',
            'scadenza_visita_medica', 'scadenza_carta_identita', 'tessera_csi', 'tessera_figc',
            'data_nascita', 'ruolo'
        )
        lista = []
        for g in giocatori:
            lista.append({
                'id': g['id'],
                'nome': g['nome_cognome'],
                'categoria': g['categoria'],
                'telefono_giocatore': g['telefono_giocatore'],
                'telefono_genitore': g['telefono_genitore'],
                'tessera_csi': g['tessera_csi'],
                'tessera_figc': g['tessera_figc'],
                'scadenza_visita_medica': str(g['scadenza_visita_medica']) if g['scadenza_visita_medica'] else None,
                'scadenza_carta_identita': str(g['scadenza_carta_identita']) if g['scadenza_carta_identita'] else None,
                'data_nascita': str(g['data_nascita']) if g['data_nascita'] else None,
                'ruolo': g['ruolo'] or 'Giocatore'
            })
        return JsonResponse({"status": "success", "giocatori": lista})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    
@csrf_exempt
def api_statistiche_giocatore(request, giocatore_id):
    try:
        # Peschiamo tutte le presenze di questo giocatore
        presenze_db = Presenza.objects.filter(giocatore_id=giocatore_id)
        
        presenze_totali = presenze_db.filter(presente=True).count()
        assenze_tot = presenze_db.filter(presente=False)
        
        # CORREZIONE: usiamo l'uguaglianza esatta, non il "contiene"
        assenze_giustificate = assenze_tot.filter(situazione='Assenza Giustificata').count()
        
        # Tutto il resto (es. 'Assenza Ingiustificata' o campi vuoti per default)
        assenze_ingiustificate = assenze_tot.exclude(situazione='Assenza Giustificata').count()

        return JsonResponse({
            "status": "success",
            "presenze_totali": str(presenze_totali),
            "assenze_giustificate": str(assenze_giustificate),
            "assenze_ingiustificate": str(assenze_ingiustificate)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def api_elimina_giocatore(request, giocatore_id):
    try:
        Giocatore.objects.get(id=giocatore_id).delete()
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)



@csrf_exempt
def api_salva_foglio_presenze(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            data_evento = data.get('data_allenamento')   # Es. '2026-09-13'
            tipo_evento = data.get('tipo_evento')          # Es. 'Allenamento' o 'Partita'
            presenze_list = data.get('presenze', [])
            firma_dispositivo = data.get('firma_dispositivo', 'Sconosciuto')

            # 1. Recuperiamo o creiamo l'oggetto Evento associato a questa data e tipo
            # (Nota: verifica che nel tuo modello Evento i campi si chiamino 'data' e 'tipo', 
            #  oppure adatta i nomi se nel tuo models.py dell'Evento si chiamano diversamente)
            evento, created = Evento.objects.get_or_create(
                data=data_evento,
                tipo=tipo_evento
            )

            # 2. Salviamo la presenza per ogni giocatore della lista
            for p in presenze_list:
                giocatore_id = p.get('giocatore_id')
                stato = p.get('stato')  # Es. 'Presente', 'Assente Giustificata', ecc.
                
                giocatore = Giocatore.objects.get(id=giocatore_id)
                
                # Mappiamo lo stato del frontend nei campi reali del database Presenza:
                is_presente = (stato == 'Presente')
                situazione_val = None if is_presente else stato

                Presenza.objects.update_or_create(
                    giocatore=giocatore,
                    evento=evento,  # <--- Usiamo la relazione corretta verso l'Evento!
                    defaults={
                        'presente': is_presente,
                        'situazione': situazione_val,
                        'firma_dispositivo': firma_dispositivo
                    }
                )

            return JsonResponse({'status': 'success', 'message': 'Presenze salvate correttamente!'})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def api_elimina_foglio_presenze(request, data_allenamento):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Metodo non consentito. Usa POST'}, status=405)
    try:
        # Trova tutti gli Eventi (allenamento/partita) di quella data,
        # poi cancella le Presenze collegate e infine l'Evento stesso.
        eventi = Evento.objects.filter(data__date=data_allenamento)
        cancellate = Presenza.objects.filter(evento__in=eventi).count()
        Presenza.objects.filter(evento__in=eventi).delete()
        eventi.delete()
        return JsonResponse({'status': 'success', 'message': f'Evento eliminato! ({cancellate} presenze rimosse)'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def api_get_presenze_data(request, data_allenamento, tipo_evento):
    try:
        # Ora peschiamo l'evento filtrando per data E per tipo
        evento = Evento.objects.filter(data=data_allenamento, tipo=tipo_evento).first()
        dati_presenze = {}
        
        if evento:
            presenze = Presenza.objects.filter(evento=evento)
            for p in presenze:
                stato = "Presente" if p.presente else (p.situazione if p.situazione else "Assenza Ingiustificata")
                dati_presenze[str(p.giocatore_id)] = stato

        return JsonResponse({"status": "success", "presenze": dati_presenze})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_statistiche_globali(request, categoria):
    try:
        # 1. ANTIPROIETTILE SULLA CATEGORIA:
        # Prendiamo solo i primi 4 caratteri (es. "2013") e cerchiamo chiunque inizi per "2013"
        # Così ignoriamo il problema di "-" o "/"
        anno_inizio = str(categoria)[:4]
        giocatori_ids = Giocatore.objects.filter(categoria__startswith=anno_inizio).values_list('id', flat=True)

        if not giocatori_ids:
            return JsonResponse({
                "status": "success", "totali": 0, "presenti": 0, "giustificate": 0, "ingiustificate": 0,
                "affluenza_giorni": {}, "andamento_mensile": {}
            })
        
        presenze = Presenza.objects.filter(giocatore_id__in=giocatori_ids)
        
        totali = presenze.count()
        presenti = presenze.filter(presente=True).count()
        
        assenze = presenze.filter(presente=False)
        giustificate = assenze.filter(situazione='Assenza Giustificata').count()
        # Tutto ciò che non è giustificato, è ingiustificato
        ingiustificate = assenze.exclude(situazione='Assenza Giustificata').count()

        giorni = {'Lunedì': 0, 'Martedì': 0, 'Mercoledì': 0, 'Giovedì': 0, 'Venerdì': 0, 'Sabato': 0, 'Domenica': 0}
        andamento = {}

        from datetime import datetime, date
        
        # Calcolo ultra-sicuro per i grafici temporali
        for p in presenze.filter(presente=True).select_related('evento'):
            if p.evento:
                d = getattr(p.evento, 'data', None)
                if d:
                    if isinstance(d, str):
                        try:
                            # Taglia a 10 caratteri per evitare orari e formatta
                            d = datetime.strptime(d[:10], '%Y-%m-%d').date()
                        except:
                            continue # Salta le date formattate male nel DB senza crashare
                    
                    if isinstance(d, (datetime, date)):
                        # Trova il giorno della settimana
                        giorno_ita = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica'][d.weekday()]
                        giorni[giorno_ita] += 1
                        
                        # Trova l'anno e il mese per la linea temporale
                        mese = d.strftime('%Y-%m')
                        andamento[mese] = andamento.get(mese, 0) + 1

        # Ordina l'andamento temporale
        andamento_ordinato = dict(sorted(andamento.items()))

        return JsonResponse({
            "status": "success",
            "totali": totali,
            "presenti": presenti,
            "giustificate": giustificate,
            "ingiustificate": ingiustificate,
            "affluenza_giorni": giorni,
            "andamento_mensile": andamento_ordinato
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": f"Errore Backend Python: {str(e)}"}, status=400)


@csrf_exempt
def api_get_date_eventi(request, tipo_evento):
    try:
        # Prende tutti gli eventi (es. 'allenamento') e li ordina dal più recente al più vecchio
        eventi = Evento.objects.filter(tipo=tipo_evento).order_by('-data')
        date_list = []
        for e in eventi:
            d = e.data
            # Normalizza la data in formato stringa YYYY-MM-DD
            data_str = d[:10] if isinstance(d, str) else d.strftime('%Y-%m-%d')
            if data_str not in date_list:
                date_list.append(data_str)
                
        return JsonResponse({"status": "success", "date": date_list})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def api_modifica_giocatore(request, giocatore_id):
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            g = Giocatore.objects.get(id=giocatore_id)
            g.nome_cognome = body.get('nome_cognome', g.nome_cognome)
            g.telefono_giocatore = body.get('telefono_giocatore', g.telefono_giocatore)
            g.telefono_genitore = body.get('telefono_genitore', g.telefono_genitore)
            g.tessera_csi = body.get('tessera_csi', g.tessera_csi)
            g.tessera_figc = body.get('tessera_figc', g.tessera_figc)
            g.ruolo = body.get('ruolo', g.ruolo)
            
            def clean_date(d):
                return d if d and str(d).strip() != '' else None
            
            if 'scadenza_visita_medica' in body:
                g.scadenza_visita_medica = clean_date(body.get('scadenza_visita_medica'))
            if 'scadenza_carta_identita' in body:
                g.scadenza_carta_identita = clean_date(body.get('scadenza_carta_identita'))
            if 'data_nascita' in body:
                g.data_nascita = clean_date(body.get('data_nascita'))
            
            g.save()
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def api_salva_log(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            LogModifica.objects.create(
                utente=data.get('utente', 'Sconosciuto'),
                azione=data.get('azione', '')
            )
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

def api_get_logs(request):
    try:
        logs = LogModifica.objects.all()[:50]
        lista = [{'data_ora': l.data_ora.strftime('%d/%m/%Y %H:%M'), 'utente': l.utente, 'azione': l.azione} for l in logs]
        return JsonResponse({'status': 'success', 'logs': lista})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
def api_risultati(request, categoria):
    if request.method == 'GET':
        risultati = Risultato.objects.filter(categoria=categoria).order_by('-data_partita')
        dati = [{'id': r.id, 'data_partita': r.data_partita.strftime('%Y-%m-%d'), 'avversario': r.avversario, 'gol_fatti': r.gol_fatti, 'gol_subiti': r.gol_subiti, 'marcatori': r.marcatori} for r in risultati]
        return JsonResponse({'status': 'success', 'risultati': dati})
    elif request.method == 'POST':
        data = json.loads(request.body)
        Risultato.objects.create(
            categoria=categoria, data_partita=data['data_partita'], avversario=data['avversario'],
            gol_fatti=data['gol_fatti'], gol_subiti=data['gol_subiti'], marcatori=data.get('marcatori', '')
        )
        return JsonResponse({'status': 'success'})

@csrf_exempt
def api_elimina_risultato(request, pk):
    Risultato.objects.filter(id=pk).delete()
    return JsonResponse({'status': 'success'})

@csrf_exempt
def api_ack_allarme(request):
    if request.method == 'GET':
        acks = AllarmeAck.objects.all()
        dati = [{'giocatore_id': a.giocatore_id, 'chiave': a.chiave_allarme} for a in acks]
        return JsonResponse({'status': 'success', 'acks': dati})
    elif request.method == 'POST':
        data = json.loads(request.body)
        AllarmeAck.objects.get_or_create(giocatore_id=data['giocatore_id'], chiave_allarme=data['chiave_allarme'])
        return JsonResponse({'status': 'success'})

import urllib.request # Mettilo in alto tra gli import se non c'è

# Incolla questo in fondo al file:

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY_2", "")

@csrf_exempt
def api_analisi_ia(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            annata = data.get('annata', 'Sconosciuta')
            classifica = data.get('classifica', [])
            risultati = data.get('risultati', [])

            prompt = f"""
            Sei 'Mastra-AI', un assistente per un allenatore di calcio giovanile in Italia (categoria {annata}).
            Ricorda che l'obiettivo primario di questa età è la CRESCITA dei ragazzi, la coesione del gruppo e il divertimento, non solo la vittoria. Tuttavia i buoni risultati aiutano il morale.

            Analizza questi dati della squadra:
            1. Dati Presenze: {json.dumps(classifica)}
            2. Ultimi Risultati Partite: {json.dumps(risultati)}

            Per favore genera un breve report diviso in:
            - VALUTAZIONE PARTECIPAZIONE: Analizza se i ragazzi vengono agli allenamenti. Chi c'è di più, chi sta mollando (troppe assenze).
            - ANALISI RISULTATI: Come stanno andando le partite. Segnamo? Subiamo troppo?
            - CONSIGLI PRATICI: Dammi 2 o 3 consigli pratici (esercizi, approccio psicologico o tattico di base) per migliorare le debolezze che vedi nei numeri, tenendo a mente la loro età. Sii conciso e diretto.
            """
                       
            
            # L'URL esatto suggerito dall'errore di Google:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            
            try:
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    testo = res_data['candidates'][0]['content']['parts'][0]['text']
                    return JsonResponse({'status': 'success', 'testo': testo})
            except urllib.error.HTTPError as e:
                errore_google = e.read().decode('utf-8')
                
                # DIAGNOSTICA AVANZATA: Chiediamo a Google quali modelli sono sbloccati per te!
                modelli_trovati = "Nessuno (Chiave bloccata o account senza permessi)"
                try:
                    url_check = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
                    with urllib.request.urlopen(urllib.request.Request(url_check)) as resp:
                        modelli = json.loads(resp.read().decode('utf-8'))
                        # Estrae solo i nomi dei modelli che contengono 'gemini'
                        modelli_trovati = ", ".join([m['name'].replace('models/', '') for m in modelli.get('models', []) if 'gemini' in m['name']])
                except Exception:
                    pass
                
                messaggio_finale = f"Errore Google:\n{errore_google}\n\n💡 I MODELLI CHE LA TUA CHIAVE PUO' USARE SONO:\n{modelli_trovati}"
                return JsonResponse({'status': 'error', 'message': messaggio_finale})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f"Errore Python: {str(e)}"})