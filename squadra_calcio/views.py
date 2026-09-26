import json
import os
import traceback
import urllib.request
import urllib.error
from functools import wraps
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Giocatore, Evento, Presenza, LogModifica, Risultato, AllarmeAck, PrenotazioneCampo, SegnalazioneScouting, DispositivoToken, LogConnessione , CacheApi , Categoria   

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render

UTENTI_DIRIGENTI = {
    'michelebiondo': '2009/2010',
    'matteoborrini': '2011/2012',
    'matteocattabiani': '2011/2012',
    'cristiancavvi': '2013/2014',
    'vincenzolama': '2009/2010',
    'vincenzolaudadio': '2011/2012',
    'andreamalpeli': '2009/2010',
    'marcospezia': '2013/2014',
    'andreatoscani': '2013/2014',
    'michelevotta': '2011/2012',
}
SUPERADMINS = ['mastra10', 'francesco11','marcoboni','gianluigibonafede']





# --- INIZIALIZZAZIONE FIREBASE ADMIN ---
if not firebase_admin._apps:
    try:
        cred_path = os.path.join(settings.BASE_DIR, 'serviceAccountKey.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin inizializzato con successo!")
    except Exception as e:
        print(f"❌ Errore inizializzazione Firebase: {e}")





def pannello_accessi_web(request):
    logs = LogConnessione.objects.all()
    oggi = timezone.now().date()

    # --- GESTIONE FILTRI ---
    filtro_oggi = request.GET.get('oggi')
    filtro_errori = request.GET.get('errori')
    filtro_utente = request.GET.get('utente', '').strip()

    if filtro_oggi == 'true':
        logs = logs.filter(data_ora__date=oggi)
    if filtro_errori == 'true':
        logs = logs.filter(status_code__gte=400) # Prende gli errori 4xx e 5xx
    if filtro_utente:
        logs = logs.filter(utente__icontains=filtro_utente)

    # --- STATISTICHE INVENTATE PER LA DASHBOARD ---
    utenti_unici_oggi = LogConnessione.objects.filter(data_ora__date=oggi).values('utente').distinct().count()
    chiamate_oggi = LogConnessione.objects.filter(data_ora__date=oggi).count()
    errori_oggi = LogConnessione.objects.filter(data_ora__date=oggi, status_code__gte=400).count()

    context = {
        'logs': logs[:300], # Mostriamo max gli ultimi 300 per non far laggare il browser
        'utenti_unici_oggi': utenti_unici_oggi,
        'chiamate_oggi': chiamate_oggi,
        'errori_oggi': errori_oggi,
        'filtro_oggi': filtro_oggi,
        'filtro_errori': filtro_errori,
        'filtro_utente': filtro_utente,
    }
    
    return render(request, 'dashboard_accessi.html', context)


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
    Schianta le richieste di utenti non autorizzati. 
    Permette la LETTURA a tutti i dirigenti registrati.
    Permette l'EDIT solo ai SuperAdmin o al dirigente per il suo specifico gruppo.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        utente_app = request.headers.get('X-Utente-App', 'Sconosciuto')
        categoria_dichiarata = request.headers.get('X-Categoria-App', '')
        
        # Normalizza l'input (minuscolo, senza spazi)
        utente_clean = utente_app.lower().replace(" ", "")
        is_admin = utente_clean in SUPERADMINS

        # 1. BARRIERA D'INGRESSO: Se non esisti, ti blocco subito
        if not is_admin and utente_clean not in UTENTI_DIRIGENTI:
            return JsonResponse({
                "status": "error", 
                "message": "Accesso negato. Utenza non riconosciuta."
            }, status=401)
            
        # I Superadmin passano sempre
        if is_admin:
            return view_func(request, *args, **kwargs)
            
        # 2. PERMESSI DI LETTURA: Tutti i dirigenti autorizzati possono leggere (GET)
        if request.method == 'GET':
            return view_func(request, *args, **kwargs)
            
        # 3. PERMESSI DI EDIT (POST): Solo sul proprio gruppo
        gruppo_assegnato = UTENTI_DIRIGENTI[utente_clean]
        categoria_url = kwargs.get('categoria', None)
        
        # Sostituisce i vecchi slash in url se necessario, o verifica diretta
        if categoria_url:
            categoria_url = categoria_url.replace('-', ' ') # Adatta al formato LAB Under X
            
        if (categoria_url and categoria_url != gruppo_assegnato) or (categoria_dichiarata != gruppo_assegnato):
            return JsonResponse({
                "status": "error", 
                "message": f"Non hai i permessi di edit. Sei autorizzato solo per: {gruppo_assegnato}"
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
                
                # --- CORREZIONE FORMATO DATE ---
                'scadenza_visita_medica': g.scadenza_visita_medica.strftime("%Y-%m-%d") if g.scadenza_visita_medica else None,
                'scadenza_carta_identita': g.scadenza_carta_identita.strftime("%Y-%m-%d") if g.scadenza_carta_identita else None,
                
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
        categoria = request.headers.get('X-Categoria-App', '').replace('-', '/')
        print(f"[DEBUG] CALENDARIO - Richiesta date per: {categoria} (Tipo: {tipo_evento})")
        
        # 🛡️ FIX: Adesso estrae SOLO le date della categoria che stai guardando!
        if categoria:
            eventi = Evento.objects.filter(tipo=tipo_evento, categoria_squadra=categoria).order_by('-data')
        else:
            eventi = Evento.objects.filter(tipo=tipo_evento).order_by('-data')
            
        date_list = []
        for e in eventi:
            d = e.data
            data_str = d[:10] if isinstance(d, str) else d.strftime('%Y-%m-%d')
            if data_str not in date_list:
                date_list.append(data_str)
                
        return JsonResponse({"status": "success", "date": date_list})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def api_salva_foglio_presenze(request):
    try:
        body = json.loads(request.body)
        data_evento = body.get('data_allenamento')
        tipo_evento = body.get('tipo_evento')
        firma = body.get('firma_dispositivo', 'Sconosciuto')
        presenze_list = body.get('presenze', [])

        categoria_header = request.headers.get('X-Categoria-App', '').replace('-', '/')
        categoria_reale = categoria_header
        
        # 🛡️ SCUDO ANTI-BUG DELL'APP: Deduce la categoria vera dai giocatori salvati!
        if presenze_list:
            primo_id = presenze_list[0].get('giocatore_id')
            giocatore_test = Giocatore.objects.filter(id=primo_id).first()
            if giocatore_test:
                categoria_reale = giocatore_test.categoria

        print(f"[DEBUG] SALVATAGGIO - Data: {data_evento}. Header App: '{categoria_header}' -> Categoria FORZATA: '{categoria_reale}'")

        if not categoria_reale:
            return JsonResponse({"status": "error", "message": "Impossibile capire l'annata"}, status=400)

        # Pulizia evento precedente della STESSA categoria
        cancellati, _ = Evento.objects.filter(data=data_evento, categoria_squadra=categoria_reale).exclude(tipo=tipo_evento).delete()
        
        evento, created = Evento.objects.get_or_create(
            data=data_evento,
            categoria_squadra=categoria_reale,
            defaults={'tipo': tipo_evento}
        )
        print(f"[DEBUG] SALVATAGGIO - Evento ID {evento.id} aggiornato/creato con successo.")
        
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
        categoria = request.headers.get('X-Categoria-App', '').replace('-', '/')
        print(f"[DEBUG] ELIMINAZIONE - Richiesta cancellazione data: {data_allenamento} per la squadra: {categoria}")

        if not categoria:
            return JsonResponse({'status': 'error', 'message': 'Categoria mancante, operazione bloccata.'}, status=400)

        eventi = Evento.objects.filter(data__date=data_allenamento, categoria_squadra=categoria)
        print(f"[DEBUG] ELIMINAZIONE - Trovati {eventi.count()} eventi da cancellare.")
        
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
        categoria = request.headers.get('X-Categoria-App', '').replace('-', '/')
        print(f"[DEBUG] LETTURA - Cerco evento il {data_allenamento} per la squadra {categoria}")
        
        evento = Evento.objects.filter(data=data_allenamento, categoria_squadra=categoria).first()
        
        dati_presenze = {}
        if evento:
            presenze = Presenza.objects.filter(evento=evento)
            for p in presenze:
                stato = "Presente" if p.presente else (p.situazione if p.situazione else "Assenza Ingiustificata")
                dati_presenze[str(p.giocatore_id)] = stato
                
            print(f"[DEBUG] LETTURA - Trovate {presenze.count()} presenze nell'evento ID {evento.id}")
            return JsonResponse({
                "status": "success", 
                "tipo_evento_salvato": evento.tipo,
                "presenze": dati_presenze
            })

        print(f"[DEBUG] LETTURA - Nessun evento trovato in questa data per i {categoria}")
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
#@check_admin_o_categoria
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

            # Normalizza la stringa per cercare sia la versione con trattino che con slash
            cat_trattino = str(annata).replace('/', '-')
            cat_slash = str(annata).replace('-', '/')

            # Cerca la cache includendo tutte le possibili formattazioni inviate dall'app
            cache = CacheApi.objects.filter(
                endpoint='analisi_ia', 
                categoria__in=[annata, cat_trattino, cat_slash]
            ).first()

            if cache and cache.payload_json:
                return JsonResponse({
                    'status': 'success', 
                    'testo': cache.payload_json
                })
            else:
                return JsonResponse({
                    'status': 'success',
                    'testo': "Mastra-AI sta analizzando i dati per la prima volta. Riprova tra qualche minuto!"
                })

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
    LATEST_VERSION = "1.0.6" 
    
    DOWNLOAD_URL = "https://performance-atlete.freeddns.org/static/fraore_lab_update.apk"
    
    return JsonResponse({
        "status": "success",
        "latest_version": LATEST_VERSION,
        "download_url": DOWNLOAD_URL,
        "release_notes": "Modifica Login e permessi"
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