import json
import os
import traceback
import urllib.request
import urllib.error
from functools import wraps
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Giocatore, Evento, Presenza, LogModifica, Risultato, AllarmeAck, PrenotazioneCampo, SegnalazioneScouting, DispositivoToken
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from datetime import timedelta


# --- INIZIALIZZAZIONE FIREBASE ADMIN ---
if not firebase_admin._apps:
    try:
        cred_path = os.path.join(settings.BASE_DIR, 'serviceAccountKey.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin inizializzato con successo!")
    except Exception as e:
        print(f"❌ Errore inizializzazione Firebase: {e}")

# --- FUNZIONE REALE PER INVIARE LA NOTIFICA ---
def invia_push_firebase(token_destinatario, titolo, corpo):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=titolo,
                body=corpo,
            ),
            token=token_destinatario,
        )
        response = messaging.send(message)
        print(f"✅ Notifica inviata con successo! ID: {response}")
    except Exception as e:
        print(f"❌ Errore nell'invio della notifica: {e}")


# ==============================================================================
# 🛡️ DECORATORE DI SICUREZZA
# ==============================================================================
def check_admin_o_categoria(view_func):
    """
    Permette la LETTURA (GET) a qualsiasi utente loggato per qualsiasi categoria (sola lettura).
    Permette la SCRITTURA/MODIFICA solo a Mastra10, Francesco11 o al mister del gruppo corrispondente.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        utente_app = request.headers.get('X-Utente-App', 'Sconosciuto')
        categoria_dichiarata = request.headers.get('X-Categoria-App', '')
        
        if request.method == 'GET':
            return view_func(request, *args, **kwargs)
            
        if utente_app in ['Mastra10', 'Francesco11']:
            return view_func(request, *args, **kwargs)
            
        categoria_url = kwargs.get('categoria', None)
        if categoria_url:
            if len(categoria_url) == 4:
                categoria_url = f"{categoria_url}/{str(int(categoria_url)+1)}"
            
            if categoria_url != categoria_dichiarata:
                return JsonResponse({
                    "status": "error", 
                    "message": "Non hai i permessi di modifica per questo gruppo. Accesso in sola lettura."
                }, status=403)
        
        return view_func(request, *args, **kwargs)
        
    return _wrapped_view


# ==============================================================================
# ⚽ API GIOCATORI
# ==============================================================================

@csrf_exempt
@check_admin_o_categoria
def api_get_giocatori(request, categoria):
    try:
        if len(categoria) == 4:
            categoria = f"{categoria}/{str(int(categoria)+1)}"
            
        anno_inizio = str(categoria)[:4]
        giocatori = Giocatore.objects.filter(categoria__startswith=anno_inizio, attivo=True)
        
        lista = []
        for g in giocatori:
            lista.append({
                'id': g.id,
                'nome': g.nome_cognome,
                'categoria': g.categoria,
                'telefono_giocatore': g.telefono_giocatore,
                'telefono_genitore': g.telefono_genitore,
                'tessera_csi': g.tessera_csi,
                'tessera_figc': g.tessera_figc,
                'scadenza_visita_medica': g.scadenza_visita_medica.strftime("%d/%m/%Y") if g.scadenza_visita_medica else None,
                'scadenza_carta_identita': g.scadenza_carta_identita.strftime("%d/%m/%Y") if g.scadenza_carta_identita else None,
                'data_nascita': g.data_nascita.strftime("%Y-%m-%d") if g.data_nascita else None,
                'ruolo': g.ruolo or 'Giocatore',
                "modulo_golee_compilato": g.modulo_golee_compilato,
                "note_mediche": g.note_mediche, 
                "certificato_scaduto": getattr(g, 'certificato_scaduto', False) 
            })
        return JsonResponse({"status": "success", "giocatori": lista})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
@check_admin_o_categoria
def api_crea_giocatore(request):
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            def clean_date(d):
                return d if d and str(d).strip() != '' else None
            
            utente_app = request.headers.get('X-Utente-App', '')
            cat_dichiarata = request.headers.get('X-Categoria-App', '')
            if utente_app not in ['Mastra10', 'Francesco11'] and body.get('categoria') != cat_dichiarata:
                 return JsonResponse({"status": "error", "message": "Non puoi creare giocatori in altre categorie"}, status=403)

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


@csrf_exempt
@check_admin_o_categoria
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
@check_admin_o_categoria
def api_elimina_giocatore(request, giocatore_id):
    try:
        Giocatore.objects.get(id=giocatore_id).delete()
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
@check_admin_o_categoria
def api_statistiche_giocatore(request, giocatore_id):
    try:
        presenze_db = Presenza.objects.filter(giocatore_id=giocatore_id)
        presenze_totali = presenze_db.filter(presente=True).count()
        assenze_tot = presenze_db.filter(presente=False)
        assenze_giustificate = assenze_tot.filter(situazione='Assenza Giustificata').count()
        assenze_ingiustificate = assenze_tot.exclude(situazione='Assenza Giustificata').count()

        return JsonResponse({
            "status": "success",
            "presenze_totali": str(presenze_totali),
            "assenze_giustificate": str(assenze_giustificate),
            "assenze_ingiustificate": str(assenze_ingiustificate)
        })
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


# ==============================================================================
# 📅 API EVENTI E PRESENZE
# ==============================================================================

@csrf_exempt
@check_admin_o_categoria
def api_get_eventi(request, categoria):
    if request.method == "GET":
        if len(categoria) == 4:
            categoria = f"{categoria}/{str(int(categoria)+1)}"
            
        eventi = Evento.objects.filter(categoria_squadra=categoria).order_by('-data')[:20]
        
        dati = []
        for e in eventi:
            dati.append({
                "id": e.id,
                "tipo": e.tipo,
                "data": e.data.strftime("%d/%m/%Y"),
                "descrizione": str(e)
            })
            
        return JsonResponse({"status": "success", "eventi": dati})


@csrf_exempt
@check_admin_o_categoria
def api_get_date_eventi(request, tipo_evento):
    try:
        eventi = Evento.objects.filter(tipo=tipo_evento).order_by('-data')
        date_list = []
        for e in eventi:
            d = e.data
            data_str = d[:10] if isinstance(d, str) else d.strftime('%Y-%m-%d')
            if data_str not in date_list:
                date_list.append(data_str)
                
        return JsonResponse({"status": "success", "date": date_list})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_salva_foglio_presenze(request):
    try:
        body = json.loads(request.body)
        data_evento = body.get('data_allenamento')
        tipo_evento = body.get('tipo_evento')
        firma = body.get('firma_dispositivo', 'Sconosciuto')
        presenze_list = body.get('presenze', [])

        # 🔥 PULIZIA: Se in questa data c'era un evento di tipo diverso, lo eliminiamo
        Evento.objects.filter(data=data_evento).exclude(tipo=tipo_evento).delete()

        evento, created = Evento.objects.get_or_create(
            data=data_evento,
            defaults={'tipo': tipo_evento}
        )
        
        for p in presenze_list:
            giocatore_id = p.get('giocatore_id')
            stato = p.get('stato')
            
            presente = (stato == 'Presente')
            situazione = '' if presente else stato

            Presenza.objects.update_or_create(
                giocatore_id=giocatore_id,
                evento=evento,
                defaults={
                    'presente': presente,
                    'situazione': situazione,
                    'firma_dispositivo': firma
                }
            )

        return JsonResponse({"status": "success"})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_elimina_foglio_presenze(request, data_allenamento):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Metodo non consentito. Usa POST'}, status=405)
    try:
        eventi = Evento.objects.filter(data__date=data_allenamento)
        cancellate = Presenza.objects.filter(evento__in=eventi).count()
        Presenza.objects.filter(evento__in=eventi).delete()
        eventi.delete()
        return JsonResponse({'status': 'success', 'message': f'Evento eliminato! ({cancellate} presenze rimosse)'})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
def api_get_presenze_data(request, data_allenamento, tipo_evento):
    try:
        evento = Evento.objects.filter(data=data_allenamento).first()
        dati_presenze = {}
        
        if evento:
            presenze = Presenza.objects.filter(evento=evento)
            for p in presenze:
                stato = "Presente" if p.presente else (p.situazione if p.situazione else "Assenza Ingiustificata")
                dati_presenze[str(p.giocatore_id)] = stato

            return JsonResponse({
                "status": "success", 
                "tipo_evento_salvato": evento.tipo,
                "presenze": dati_presenze
            })

        return JsonResponse({"status": "success", "presenze": None})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


# ==============================================================================
# 📊 API STATISTICHE E RISULTATI
# ==============================================================================

@csrf_exempt
@check_admin_o_categoria
def api_statistiche_globali(request, categoria):
    try:
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
        ingiustificate = assenze.exclude(situazione='Assenza Giustificata').count()

        giorni = {'Lunedì': 0, 'Martedì': 0, 'Mercoledì': 0, 'Giovedì': 0, 'Venerdì': 0, 'Sabato': 0, 'Domenica': 0}
        andamento = {}

        from datetime import datetime, date
        for p in presenze.filter(presente=True).select_related('evento'):
            if p.evento:
                d = getattr(p.evento, 'data', None)
                if d:
                    if isinstance(d, str):
                        try:
                            d = datetime.strptime(d[:10], '%Y-%m-%d').date()
                        except:
                            continue 
                    
                    if isinstance(d, (datetime, date)):
                        giorno_ita = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica'][d.weekday()]
                        giorni[giorno_ita] += 1
                        mese = d.strftime('%Y-%m')
                        andamento[mese] = andamento.get(mese, 0) + 1

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
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": f"Errore Backend Python: {str(e)}"}, status=400)


@csrf_exempt
@check_admin_o_categoria
def api_risultati(request, categoria):
    try:
        # Creiamo entrambe le varianti per sicurezza
        cat_trattino = str(categoria).replace('/', '-')
        cat_slash = str(categoria).replace('-', '/')
        
        if request.method == 'GET':
            # Cerchiamo i risultati che corrispondono all'una o all'altra formattazione
            risultati = Risultato.objects.filter(categoria__in=[categoria, cat_trattino, cat_slash]).order_by('-data_partita')
            dati = [{'id': r.id, 'data_partita': r.data_partita.strftime('%Y-%m-%d'), 'avversario': r.avversario, 'gol_fatti': r.gol_fatti, 'gol_subiti': r.gol_subiti, 'marcatori': r.marcatori} for r in risultati]
            return JsonResponse({'status': 'success', 'risultati': dati})
            
        elif request.method == 'POST':
            data = json.loads(request.body)
            Risultato.objects.create(
                categoria=categoria, 
                data_partita=data['data_partita'], 
                avversario=data['avversario'],
                gol_fatti=data['gol_fatti'], 
                gol_subiti=data['gol_subiti'], 
                marcatori=data.get('marcatori', '')
            )
            return JsonResponse({'status': 'success'})
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': f"Errore Risultati: {str(e)}"}, status=400)


@csrf_exempt
def api_elimina_risultato(request, pk):
    Risultato.objects.filter(id=pk).delete()
    return JsonResponse({'status': 'success'})


# ==============================================================================
# 📝 API DI SERVIZIO E INTELLIGENZA ARTIFICIALE
# ==============================================================================

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
def api_ack_allarme(request):
    if request.method == 'GET':
        acks = AllarmeAck.objects.all()
        dati = [{'giocatore_id': a.giocatore_id, 'chiave': a.chiave_allarme} for a in acks]
        return JsonResponse({'status': 'success', 'acks': dati})
    elif request.method == 'POST':
        data = json.loads(request.body)
        AllarmeAck.objects.get_or_create(giocatore_id=data['giocatore_id'], chiave_allarme=data['chiave_allarme'])
        return JsonResponse({'status': 'success'})


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
                
                messaggio_finale = f"Errore Google:\n{errore_google}"
                return JsonResponse({'status': 'error', 'message': messaggio_finale})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f"Errore Python: {str(e)}"})


@csrf_exempt
def api_scouting(request):
    try:
        if request.method == 'GET':
            scouts = SegnalazioneScouting.objects.all().order_by('-data_creazione')
            data = [{"id": s.id, "squadra": s.squadra_avversaria, "categoria": s.categoria_avversaria, "nome": s.nome_giocatore, "note": s.note, "segnalatore": s.segnalatore, "data": s.data_creazione.strftime("%d/%m/%Y")} for s in scouts]
            return JsonResponse({"status": "success", "scouting": data})
        elif request.method == 'POST':
            body = json.loads(request.body)
            SegnalazioneScouting.objects.create(
                squadra_avversaria=body.get('squadra', ''),
                categoria_avversaria=body.get('categoria', ''),
                nome_giocatore=body.get('nome', ''),
                note=body.get('note', ''),
                segnalatore=request.headers.get('X-Utente-App', 'Sconosciuto')
            )
            return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Errore DB Scouting: {str(e)}"}, status=400)


@csrf_exempt
@check_admin_o_categoria
def api_elimina_scouting(request, pk):
    try:
        s = SegnalazioneScouting.objects.get(id=pk)
        utente_app = request.headers.get('X-Utente-App', '')
        if utente_app not in ['Mastra10', 'Francesco11'] and s.segnalatore != utente_app:
            return JsonResponse({"status": "error", "message": "Non puoi eliminare una segnalazione fatta da altri."}, status=403)
            
        s.delete()
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Errore: {str(e)}"}, status=400)


@csrf_exempt
def api_prenotazioni(request):
    try:
        if request.method == 'GET':
            prenotazioni = PrenotazioneCampo.objects.all().order_by('data_ora_inizio')
            data = [{
                "id": p.id, "data_inizio": p.data_ora_inizio.isoformat(), "data_fine": p.data_ora_fine.isoformat(),
                "categoria": p.categoria_richiedente, "avversario": p.avversario, "stato": p.stato,
                "richiedente": p.richiedente, "note": p.note
            } for p in prenotazioni]
            return JsonResponse({"status": "success", "prenotazioni": data})
            
        elif request.method == 'POST':
            body = json.loads(request.body)
            richiedente = request.headers.get('X-Utente-App', 'Sconosciuto')
            avversario = body.get('avversario', '')
            
            PrenotazioneCampo.objects.create(
                data_ora_inizio=body['data_inizio'],
                data_ora_fine=body['data_fine'],
                categoria_richiedente=body.get('categoria', '').replace('-', '/'),
                avversario=avversario,
                note=body.get('note', ''),
                richiedente=richiedente
            )
            
            try:
                admins_possibili = ['Mastra10', 'Francesco11', 'mastra10', 'francesco11']
                tokens_admin = DispositivoToken.objects.filter(utente__in=admins_possibili)
                
                for admin_dispositivo in tokens_admin:
                    if admin_dispositivo.token_fcm:
                        invia_push_firebase(
                            admin_dispositivo.token_fcm,
                            "⚽ Nuova Richiesta Campo",
                            f"Il Mister {richiedente} ha richiesto il campo per {avversario}."
                        )
                print("Notifica di richiesta campo inviata agli admin.")
            except Exception as notif_err:
                print(f"Errore nell'invio ai Superadmin: {notif_err}")

            return JsonResponse({"status": "success"})
            
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": f"Errore DB Prenotazioni: {str(e)}"}, status=400)


@csrf_exempt
def api_approva_prenotazione(request, pk):
    try:
        utente = request.headers.get('X-Utente-App', '')
        if utente not in ['Mastra10', 'Francesco11']:
            return JsonResponse({"status": "error", "message": "Solo gli admin possono approvare i campi."}, status=403)
            
        body = json.loads(request.body)
        nuovo_stato = body.get('stato')
        
        p = PrenotazioneCampo.objects.get(id=pk)
        p.stato = nuovo_stato
        p.save()
        
        try:
            dispositivo = DispositivoToken.objects.filter(utente=p.richiedente).first()
            if dispositivo and dispositivo.token_fcm:
                icona = "✅" if nuovo_stato == 'Approvata' else "❌"
                
                invia_push_firebase(
                    dispositivo.token_fcm,
                    f"Prenotazione {nuovo_stato} {icona}",
                    f"La tua richiesta per {p.avversario} è stata {nuovo_stato.lower()}."
                )
                print(f"Notifica inviata con successo a {p.richiedente}!")
        except Exception as notif_err:
            print(f"Errore notifica: {notif_err}")

        return JsonResponse({"status": "success"})
        
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": f"Errore approvazione: {str(e)}"}, status=400)


@csrf_exempt
def api_elimina_prenotazione(request, pk):
    try:
        utente = request.headers.get('X-Utente-App', '')
        p = PrenotazioneCampo.objects.get(id=pk)
        
        # Verifichiamo i permessi (solo chi ha creato la richiesta o gli admin possono cancellarla)
        admins_possibili = ['Mastra10', 'Francesco11', 'mastra10', 'francesco11']
        is_admin = utente in admins_possibili
        
        if p.richiedente != utente and not is_admin:
            return JsonResponse({"status": "error", "message": "Non hai i permessi per eliminare questa prenotazione."}, status=403)
        
        avversario = p.avversario
        richiedente = p.richiedente
        
        # Eliminiamo la prenotazione dal database
        p.delete()
        
        # 🔔 INVIA NOTIFICA AGLI ADMIN (Solo se ad annullare è il Mister)
        if not is_admin and richiedente == utente:
            try:
                tokens_admin = DispositivoToken.objects.filter(utente__in=admins_possibili)
                for admin_dispositivo in tokens_admin:
                    if admin_dispositivo.token_fcm:
                        invia_push_firebase(
                            admin_dispositivo.token_fcm,
                            "❌ Prenotazione Annullata",
                            f"Il Mister {richiedente} ha annullato la richiesta campo per {avversario}."
                        )
                print(f"Notifica di annullamento inviata agli admin.")
            except Exception as notif_err:
                print(f"Errore notifica annullamento: {notif_err}")

        return JsonResponse({"status": "success"})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_salva_token_fcm(request):
    try:
        utente = request.headers.get('X-Utente-App', '')
        if not utente:
            return JsonResponse({"status": "error", "message": "Utente mancante"}, status=400)

        body = json.loads(request.body)
        nuovo_token = body.get('token')

        if nuovo_token:
            DispositivoToken.objects.filter(token_fcm=nuovo_token).exclude(utente=utente).delete()

            DispositivoToken.objects.update_or_create(
                utente=utente,
                defaults={'token_fcm': nuovo_token}
            )
            print(f"Token registrato in modo sicuro per {utente}")
            
        return JsonResponse({"status": "success"})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_check_update(request):
    LATEST_VERSION = "1.0.2" 
    
    DOWNLOAD_URL = "https://performance-atlete.freeddns.org/static/fraore_lab_update.apk"
    
    return JsonResponse({
        "status": "success",
        "latest_version": LATEST_VERSION,
        "download_url": DOWNLOAD_URL,
        "release_notes": "Aggiunta eliminazione prenotazioni e fix presenze."
    })



from datetime import timedelta

from datetime import timedelta

@csrf_exempt
@check_admin_o_categoria
def api_andamento_chart(request, categoria):
    try:
        cat_trattino = str(categoria).replace('/', '-')
        cat_slash = str(categoria).replace('-', '/')
        
        partite = Risultato.objects.filter(categoria__in=[categoria, cat_trattino, cat_slash]).order_by('data_partita')
        
        anno_inizio = str(categoria)[:4]
        giocatori_ids = list(Giocatore.objects.filter(categoria__startswith=anno_inizio).values_list('id', flat=True))
        
        dati_grafico = []
        
        for p in partite:
            if not p.data_partita: continue
            
            # Ricerca presenze allargata a 30 giorni prima della partita
            data_fine = p.data_partita
            data_inizio = data_fine - timedelta(days=30)
            
            presenze_periodo = Presenza.objects.filter(
                giocatore_id__in=giocatori_ids,
                evento__tipo__iexact='allenamento',
                evento__data__date__gte=data_inizio,
                evento__data__date__lte=data_fine
            )
            
            totali = presenze_periodo.count()
            presenti = presenze_periodo.filter(presente=True).count()
            perc_pres = round((presenti / totali) * 100, 1) if totali > 0 else 0.0
            
            if p.gol_fatti > p.gol_subiti: rendimento = 100.0
            elif p.gol_fatti == p.gol_subiti: rendimento = 50.0
            else: rendimento = 0.0
            
            etichetta = data_fine.strftime('%d/%m')
            
            dati_grafico.append({
                "etichetta": f"{etichetta}\n{p.avversario[:5]}",
                "rendimento_partite": rendimento,
                "perc_presenze": perc_pres
            })
            
        return JsonResponse({"status": "success", "dati": dati_grafico})
        
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Errore Andamento: {str(e)}"}, status=400)