import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Giocatore, Evento, Presenza
import traceback

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
    """
    Riceve i dati dall'app e crea un nuovo giocatore nel database.
    """
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            
            # Estraiamo chi ha fatto l'operazione per i log
            firma_dispositivo = body.get('firma_dispositivo', 'Sconosciuto')
            
            # Creazione del record
            nuovo_giocatore = Giocatore.objects.create(
                nome_cognome=body.get('nome_cognome'),
                categoria=body.get('categoria'),
                telefono_giocatore=body.get('telefono_giocatore', ''),
                telefono_genitore=body.get('telefono_genitore', ''),
                note_mediche=body.get('note_mediche', '')
            )
            
            # Stampa nel terminale di Django per debug/storico
            print(f"[{firma_dispositivo}] ha aggiunto un nuovo giocatore: {nuovo_giocatore.nome_cognome}")
            
            return JsonResponse({
                "status": "success", 
                "message": "Giocatore creato con successo!",
                "giocatore_id": nuovo_giocatore.id
            })
            
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
            
    return JsonResponse({"status": "error", "message": "Metodo non consentito. Usa POST"}, status=405)


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
            
            # Gestione sicura delle date
            visita = body.get('scadenza_visita_medica')
            g.scadenza_visita_medica = visita if visita else None
            
            carta = body.get('scadenza_carta_identita')
            g.scadenza_carta_identita = carta if carta else None
            
            g.save()
            return JsonResponse({"status": "success"})
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
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            data_allenamento = body.get('data_allenamento')
            tipo_evento = body.get('tipo_evento', 'allenamento') # Legge se è partita o allenamento
            presenze_list = body.get('presenze', []) 
            firma = body.get('firma_dispositivo', 'Sconosciuto')

            # Troviamo o creiamo l'evento filtrando ANCHE per il tipo
            evento, created = Evento.objects.get_or_create(
                data=data_allenamento,
                tipo=tipo_evento,
                defaults={'note_evento': f'Generato da app il {data_allenamento}'}
            )

            for p in presenze_list:
                giocatore_id = p.get('giocatore_id')
                stato = p.get('stato', 'Assenza Ingiustificata')
                presente = (stato == 'Presente')
                situazione = '' if presente else stato

                Presenza.objects.update_or_create(
                    giocatore_id=giocatore_id,
                    evento=evento,
                    defaults={'presente': presente, 'situazione': situazione, 'firma_dispositivo': firma}
                )
            return JsonResponse({"status": "success"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

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