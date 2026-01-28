import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from allauth.socialaccount.models import SocialToken ,SocialAccount
from django.core.cache import cache
from .models import Attivita, ProfiloAtleta
import math
from .utils import analizza_performance_atleta, calcola_metrica_vo2max, stima_vo2max_atleta, stima_potenza_watt, calcola_trend_atleta, formatta_passo, stima_potenziale_gara, analizza_squadra_coach, calcola_vam_selettiva, refresh_strava_token, processa_attivita_strava
import time
from django.db.models import Sum, Max, Q, OuterRef, Subquery
from django.utils import timezone
from datetime import timedelta
import json
from django.contrib.auth.models import User
import csv
from django_apscheduler.models import DjangoJobExecution, DjangoJob
from .models import TaskSettings
from django.core.management import call_command
from django.contrib import messages
from datetime import timedelta
from django.template.loader import render_to_string
import os

def _get_dashboard_context(user):
    """Helper per generare il contesto della dashboard per un dato utente"""
        # Recuperiamo il profilo
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=user)
        
        # 1. Calcolo KM Totali (da metri a km)
    metri = Attivita.objects.filter(atleta=profilo).aggregate(Sum('distanza'))['distanza__sum'] or 0
    totale_km = round(metri / 1000, 1)
        
        # 2. Recupero le ultime 10 attività per la tabella
    attivita_list = Attivita.objects.filter(atleta=profilo).order_by('-data')[:10]
        
        # 3. Dati per i grafici Dashboard (Ultime 30 attività)
    qs_charts = Attivita.objects.filter(atleta=profilo).order_by('-data')[:30]
    chart_data = list(reversed(qs_charts))
        
        # Calcolo VAM Media (usiamo chart_data che è già una lista caricata)
    vam_values = [a.vam for a in chart_data if a.vam > 0]
    vam_media = int(sum(vam_values) / len(vam_values)) if vam_values else 0
        
        # Calcolo Potenza Media (su attività con potenza > 0)
    power_values = [a.potenza_media for a in chart_data if a.potenza_media and a.potenza_media > 0]
    potenza_media = int(sum(power_values) / len(power_values)) if power_values else 0
        
        # Calcolo FC Media Recente (ultime 30)
    fc_values = [a.fc_media for a in chart_data if a.fc_media]
    fc_media_recent = int(sum(fc_values) / len(fc_values)) if fc_values else 0
        
        # Calcolo Passo Medio Recente (ultime 30)
    speeds = [a.distanza / a.durata for a in chart_data if a.durata > 0]
    avg_speed = sum(speeds) / len(speeds) if speeds else 0
    passo_media_recent = formatta_passo(avg_speed)

        # Calcolo Livello VO2max (Scala Endurance Maschile)
    livello_vo2max = ""
    if profilo.vo2max_stima_statistica:
        val = profilo.vo2max_stima_statistica
        if val >= 65: livello_vo2max = "Elite 🏆"
        elif val >= 58: livello_vo2max = "Eccellente 🥇"
        elif val >= 52: livello_vo2max = "Ottimo 🥈"
        elif val >= 45: livello_vo2max = "Buono 🥉"
        else: livello_vo2max = "Normale"

        # Calcolo Livello VO2max Strada
    livello_vo2max_strada = ""
    if profilo.vo2max_strada:
        val = profilo.vo2max_strada
        if val >= 65: livello_vo2max_strada = "Elite 🏆"
        elif val >= 58: livello_vo2max_strada = "Eccellente 🥇"
        elif val >= 52: livello_vo2max_strada = "Ottimo 🥈"
        elif val >= 45: livello_vo2max_strada = "Buono 🥉"
        else: livello_vo2max_strada = "Normale"
            
        # Calcolo Livello VAM (m/h su attività con dislivello)
    livello_vam = ""
    if vam_media > 0:
        if vam_media >= 1000: livello_vam = "Grimpeur Elite 🧗"
        elif vam_media >= 800: livello_vam = "Eccellente 🏔️"
        elif vam_media >= 600: livello_vam = "Ottimo ⛰️"
        elif vam_media >= 400: livello_vam = "Buono 🥾"
        else: livello_vam = "Base"

        # Calcolo Livello Potenza (W/kg)
    livello_potenza = ""
    if potenza_media > 0 and profilo.peso:
        w_kg = potenza_media / profilo.peso
        if w_kg >= 4.0: livello_potenza = "Elite ⚡"
        elif w_kg >= 3.4: livello_potenza = "Eccellente 🔥"
        elif w_kg >= 2.8: livello_potenza = "Ottimo 🚀"
        elif w_kg >= 2.2: livello_potenza = "Buono 🏃"
        else: livello_potenza = "Base"

        # Calcolo Livello ITRA
    livello_itra = ""
    if profilo.indice_itra > 0:
        val = profilo.indice_itra
        if val >= 825: livello_itra = "Elite Int. 🌍"
        elif val >= 725: livello_itra = "Elite Naz. 🇮🇹"
        elif val >= 625: livello_itra = "Avanzato 🏃"
        elif val >= 500: livello_itra = "Intermedio 👍"
        else: livello_itra = "Amateur"

        # Calcolo Livello UTMB
    livello_utmb = ""
    if profilo.indice_utmb > 0:
        val = profilo.indice_utmb
        if val >= 825: livello_utmb = "Elite Int. 🌍"
        elif val >= 725: livello_utmb = "Elite Naz. 🇮🇹"
        elif val >= 625: livello_utmb = "Avanzato 🏃"
        elif val >= 500: livello_utmb = "Intermedio 👍"
        else: livello_utmb = "Amateur"
        
        # Calcolo Soglie Cardiache Stimata (Karvonen)
    soglia_aerobica = 0
    soglia_anaerobica = 0
    if profilo.fc_max and profilo.fc_riposo:
        hrr = profilo.fc_max - profilo.fc_riposo
            # AeT (Aerobic Threshold) ~72% HRR (Top Z2 / Inizio Z3) - Ritmo Lungo Svelto
        soglia_aerobica = int(profilo.fc_riposo + (hrr * 0.72))
            # AnT (Anaerobic Threshold) ~90% HRR (Top Z4) - Ritmo Gara 10k/Mezza
        soglia_anaerobica = int(profilo.fc_riposo + (hrr * 0.90))

        # Calcolo Trend (Andamento Recente vs Storico)
    trends = calcola_trend_atleta(profilo)

    labels = []
    fc_data = []
    pace_data = [] 
    dist_data = []
    power_data = []
    elev_data = []
        
    for act in chart_data:
            # FILTRO OUTLIER AGGRESSIVO: Ignoriamo attività > 100km o con dislivello > 5000m
            # Questo risolve il problema del grafico "piatto" causato da record errati (es. 18.000km)
        if act.distanza > 100000 or act.dislivello > 5000: 
            continue

        labels.append(act.data.strftime("%d/%m"))
        fc_data.append(act.fc_media if act.fc_media else None)
        dist_data.append(round(act.distanza / 1000, 2))
        power_data.append(act.potenza_media if act.potenza_media else None)
        elev_data.append(act.dislivello)
            
            # Calcolo passo in minuti decimali (es. 5.5 = 5:30) per il grafico
        if act.distanza > 0:
            pace_min_km = (act.durata / 60) / (act.distanza / 1000)
            pace_data.append(round(pace_min_km, 2))
        else:
            pace_data.append(None)

    # Warning Peso
    warning_peso = None
    if not profilo.peso or profilo.peso <= 0:
        warning_peso = "Peso non configurato per l'atleta! Fondamentale impostarlo nei settings. Stiamo assumendo un valore di default (70kg) per i calcoli."

    return {
        'totale_km': totale_km,
        'vam_media': vam_media,
        'potenza_media': potenza_media,
        'fc_media_recent': fc_media_recent,
        'passo_media_recent': passo_media_recent,
        'livello_vo2max': livello_vo2max,
        'livello_vo2max_strada': livello_vo2max_strada,
        'livello_vam': livello_vam,
        'livello_potenza': livello_potenza,
        'livello_itra': livello_itra,
        'livello_utmb': livello_utmb,
        'soglia_aerobica': soglia_aerobica,
        'soglia_anaerobica': soglia_anaerobica,
        'trends': trends,
        'attivita_recenti': attivita_list,
        'profilo': profilo,
        'chart_labels': json.dumps(labels),
        'chart_fc': json.dumps(fc_data),
        'chart_pace': json.dumps(pace_data),
        'chart_dist': json.dumps(dist_data),
        'chart_power': json.dumps(power_data),
        'chart_elev': json.dumps(elev_data),
        'vam_tooltip': "VAM Selettiva (Pro): Calcolata isolando solo i tratti di salita con pendenza > 7% (dati reali secondo per secondo). Esclude pause, discese e tratti in piano per riflettere la tua vera velocità ascensionale.",
        'warning_peso': warning_peso,
    }

# 1. Questa mostra la pagina (NON cancellarla!)
def home(request):
    # Endpoint per polling stato sync (chiamato via AJAX dal modal)
    if request.GET.get('sync_status'):
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'Login richiesto', 'progress': 0}, status=401)
            
        status = cache.get(f"sync_progress_{request.user.id}", {'status': 'In attesa...', 'progress': 0})
        return JsonResponse(status)

    if request.user.is_authenticated:
        context = _get_dashboard_context(request.user)
        return render(request, 'atleti/home.html', context)
    return render(request, 'atleti/home.html')

def dashboard_atleta(request, username):
    """Visualizza la dashboard di un altro atleta se permesso"""
    target_user = get_object_or_404(User, username=username)
    profilo = get_object_or_404(ProfiloAtleta, user=target_user)
    
    # Controllo Permessi:
    # 1. È l'utente stesso
    # 2. È un admin (staff)
    # 3. L'utente ha reso la dashboard pubblica
    if request.user == target_user or request.user.is_staff or profilo.dashboard_pubblica:
        context = _get_dashboard_context(target_user)
        return render(request, 'atleti/home.html', context)
    else:
        return render(request, 'atleti/home.html', {
            'error_message': f"La dashboard di {target_user.first_name} è privata."
        })


def analisi_gemini(request):
    profilo = request.user.profiloatleta
    commento_ai = analizza_performance_atleta(profilo)
    
    # Salviamo il commento nel profilo per non perderlo
    profilo.ultima_analisi_ai = commento_ai
    profilo.save()
    
    return render(request, 'atleti/home.html', {'analisi': commento_ai})


def calcola_vo2max(request):
    if request.method == 'POST':
        print("DEBUG: Avvio richiesta calcolo VO2max...", flush=True)
        profilo = request.user.profiloatleta
        hr_rest = request.POST.get('hr_rest')
        
        if hr_rest:
            profilo.fc_riposo = int(hr_rest) # Corretto nome campo
            profilo.save()
            print(f"DEBUG: Battito a riposo salvato: {hr_rest}", flush=True)

            # Chiamata a Gemini
            try:
                print("DEBUG: Chiamata a Gemini in corso...", flush=True)
                analisi_testo = analizza_performance_atleta(profilo)
                
                if analisi_testo:
                    profilo.ultima_analisi_ai = analisi_testo
                    profilo.save()
                    print("DEBUG: ANALISI SALVATA CORRETTAMENTE NEL DB!", flush=True)
                else:
                    print("DEBUG: ATTENZIONE - Gemini ha restituito una risposta vuota", flush=True)
            except Exception as e:
                print(f"DEBUG ERRORE DURANTE L'ANALISI: {e}", flush=True)
        else:
            print("DEBUG: Errore - HR Rest non ricevuto dal form", flush=True)
            
    return redirect('home')

def impostazioni(request):
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        try:
            peso = float(request.POST.get('peso'))
            fc_riposo = int(request.POST.get('fc_riposo'))
            fc_max = int(request.POST.get('fc_max'))
            
            # Nuovi campi impostazioni
            mostra_peso = request.POST.get('mostra_peso') == 'on'
            dashboard_pubblica = request.POST.get('dashboard_pubblica') == 'on'
            indice_itra = int(request.POST.get('indice_itra') or 0)
            indice_utmb = int(request.POST.get('indice_utmb') or 0)
            
            profilo.peso = peso
            profilo.mostra_peso = mostra_peso
            profilo.dashboard_pubblica = dashboard_pubblica
            profilo.fc_riposo = fc_riposo
            profilo.fc_max = fc_max
            profilo.fc_massima_teorica = fc_max
            
            # Gestione checkbox manuale
            if request.POST.get('fc_max_manuale') == 'on':
                profilo.fc_max_manuale = True
                profilo.data_fc_max = None
            else:
                profilo.fc_max_manuale = False
                
            if indice_itra > 0: profilo.indice_itra = indice_itra
            if indice_utmb > 0: profilo.indice_utmb = indice_utmb
            profilo.save()
            return redirect('home')
        except ValueError:
            pass
    return render(request, 'atleti/impostazioni.html', {'profilo': profilo})

def aggiorna_dati_profilo(request):
    """Forza l'aggiornamento dei dati anagrafici (Peso, Nome) da Strava/SocialAccount senza sync attività"""
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    social_acc = SocialAccount.objects.filter(user=request.user, provider='strava').first()
    
    if social_acc and social_acc.extra_data:
        # 1. Prova a prendere il peso dai dati di login salvati (spesso più completi dell'API)
        weight = social_acc.extra_data.get('weight')
        if weight:
            profilo.peso = weight
            profilo.save()
            print(f"DEBUG: Profilo aggiornato manualmente da SocialAccount. Peso: {weight}", flush=True)
        
        # Recuperiamo anche l'immagine profilo
        img_url = social_acc.extra_data.get('profile')
        if img_url:
            profilo.immagine_profilo = img_url
            profilo.save()
            
        # Aggiorna anche nome/cognome se presenti
        # (omesso per brevità, il peso è la priorità)
            
    return redirect('impostazioni')

@login_required
def sincronizza_strava(request):
    print("DEBUG: Avvio sincronizzazione...", flush=True)
    cache_key = f"sync_progress_{request.user.id}"
    cache.set(cache_key, {'status': 'Connessione a Strava...', 'progress': 5}, timeout=300)
    
    social_acc = SocialAccount.objects.filter(user=request.user, provider='strava').first()
    if not social_acc:
        print("DEBUG: ESCI - SocialAccount non trovato", flush=True)
        messages.error(request, "Nessun account Strava collegato. Vai nelle impostazioni.")
        return redirect('home')

    token_obj = SocialToken.objects.filter(account=social_acc).first()
    if not token_obj:
        print("DEBUG: ESCI - SocialToken non trovato", flush=True)
        messages.error(request, "Token Strava mancante o scaduto. Prova a scollegare e ricollegare l'account.")
        return redirect('home')

    print(f"DEBUG: Token trovato! Procedo con Strava per {request.user.username}", flush=True)
    
    # 1. Refresh Token (Nuova logica centralizzata)
    access_token = refresh_strava_token(token_obj)
    if not access_token:
        print("DEBUG: Token scaduto e refresh fallito. Reindirizzo al login.", flush=True)
        return redirect('/accounts/strava/login/')
        
    headers = {'Authorization': f'Bearer {access_token}'}

    cache.set(cache_key, {'status': 'Aggiornamento profilo...', 'progress': 10}, timeout=300)
    # --- 2. DATI PROFILO (PESO E NOMI) ---
    athlete_res = requests.get("https://www.strava.com/api/v3/athlete", headers=headers)
    
    if athlete_res.status_code == 401:
        print("DEBUG: Token scaduto (Profilo). Reindirizzo al login Strava per refresh.", flush=True)
        return redirect('/accounts/strava/login/')

    # Aggiorniamo il profilo atleta
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)

    # Recuperiamo il peso dai dati di login (extra_data) che spesso sono più completi dell'API limitata
    if social_acc.extra_data and social_acc.extra_data.get('weight'):
        weight_extra = social_acc.extra_data.get('weight')
        profilo.peso = weight_extra
        print(f"DEBUG: Peso recuperato da SocialAccount: {weight_extra}", flush=True)
        
        # Recuperiamo immagine da SocialAccount come fallback/init
        img_extra = social_acc.extra_data.get('profile')
        if img_extra:
            profilo.immagine_profilo = img_extra

    if athlete_res.status_code == 200:
        athlete_data = athlete_res.json()
        # Aggiorniamo il peso SOLO se Strava ce lo fornisce (evita sovrascrittura con 70kg)
        strava_weight = athlete_data.get('weight')
        if strava_weight:
            profilo.peso = strava_weight
        
        # Aggiorniamo immagine profilo dall'API (più recente)
        strava_img = athlete_data.get('profile')
        if strava_img:
            profilo.immagine_profilo = strava_img
            
        request.user.first_name = athlete_data.get('firstname', '')
        request.user.last_name = athlete_data.get('lastname', '')
        request.user.save()
    profilo.save()

    # --- CHECK BLOCCANTE: Se mancano Peso o FC Riposo, STOP ---
    if not profilo.peso or not profilo.fc_riposo:
        print("DEBUG: Dati profilo mancanti. Reindirizzo a impostazioni.", flush=True)
        return redirect('impostazioni')

    # --- 4. SCARICAMENTO ATTIVITÀ (FULL SYNC + CHECKPOINT) ---
    # Cerchiamo l'ultima attività salvata per usare il parametro 'after' (Checkpoint)
    last_activity = Attivita.objects.filter(atleta=profilo).order_by('-data').first()
    timestamp_checkpoint = None
    
    if last_activity:
        # Aggiungiamo 1 secondo per non riscaricare l'ultima attività
        timestamp_checkpoint = int(last_activity.data.timestamp()) + 1
        print(f"DEBUG: Checkpoint trovato: {last_activity.data} (Epoch: {timestamp_checkpoint})", flush=True)
    else:
        print("DEBUG: Nessuna attività precedente (Primo Download Completo).", flush=True)

    url_activities = "https://www.strava.com/api/v3/athlete/activities"
    
    page = 1
    per_page = 100 # Ottimizzazione: scarichiamo blocchi più grandi (max supportato ~200)
    
    while True:
        params = {'page': page, 'per_page': per_page}
        cache.set(cache_key, {'status': f'Scaricamento attività (Pagina {page})...', 'progress': min(15 + (page * 10), 80)}, timeout=300)
        if timestamp_checkpoint:
            params['after'] = timestamp_checkpoint
            
        response = requests.get(url_activities, headers=headers, params=params)
        
        print(f"DEBUG: Richiesta Strava (Pagina {page}) - Status: {response.status_code}", flush=True)

        if response.status_code == 401:
            print("DEBUG: Token scaduto (Attività). Reindirizzo al login Strava per refresh.", flush=True)
            return redirect('/accounts/strava/login/')

        if response.status_code == 429:
            print("DEBUG: ⚠️ LIMITE API STRAVA RAGGIUNTO. Sincronizzazione parziale interrotta.", flush=True)
            break

        if response.status_code != 200:
            print(f"DEBUG: Errore API: {response.text}", flush=True)
            break
            
        activities = response.json()
        if not activities:
            print("DEBUG: Nessuna altra attività trovata. Sync completato.", flush=True)
            break
            
        print(f"DEBUG: Attività trovate pagina {page}: {len(activities)}", flush=True)

        for act in activities:
            # Aggiunto supporto per Hike (Trekking) trattato come Trail
            if act['type'] in ['Run', 'TrailRun', 'Hike']:
                # Usiamo la nuova utility centralizzata
                processa_attivita_strava(act, profilo, access_token)
        
        # Se la pagina è incompleta, significa che abbiamo finito
        if len(activities) < per_page:
            break
            
        page += 1

    cache.set(cache_key, {'status': 'Analisi fisiologica e statistiche...', 'progress': 90}, timeout=300)
    # --- 8. AUTO-CALCOLO FC MAX REALE ---
    # Modifica: cattura la fc max degli ultimi 5 mesi (approx 150 giorni)
    five_months_ago = timezone.now() - timedelta(days=150)
    
    # Cerchiamo l'attività con la FC più alta nel periodo per estrarre anche la data
    best_activity = Attivita.objects.filter(
        atleta=profilo, 
        data__gte=five_months_ago,
        fc_max_sessione__gt=160  # Filtriamo valori non fisiologici/bassi
    ).order_by('-fc_max_sessione').first()
    
    if best_activity:
        max_fc_reale = best_activity.fc_max_sessione
        data_record = best_activity.data.strftime('%d/%m/%Y')
        data_obj = best_activity.data.date()
        
        # Aggiorniamo il profilo al "Season Best" (ultimi 5 mesi).
        # FIX: Se l'utente ha impostato la FC manualmente, NON sovrascriviamo.
        if not profilo.fc_max_manuale:
            profilo.fc_massima_teorica = max_fc_reale
            profilo.fc_max = max_fc_reale
            profilo.data_fc_max = data_obj
            profilo.save()
            print(f"DEBUG: FC Max rilevata (ultimi 5 mesi): {max_fc_reale} bpm il {data_record}", flush=True)
        else:
            print(f"DEBUG: FC Max rilevata {max_fc_reale} (il {data_record}) ma IGNORATA perché impostata manualmente.", flush=True)

    # --- 9. CALCOLO VO2MAX CONSOLIDATO (MEDIA MOBILE) ---
    stima_vo2max_atleta(profilo)

    cache.set(cache_key, {'status': 'Completato!', 'progress': 100}, timeout=300)
    return redirect('home')

def grafici_atleta(request):
    if not request.user.is_authenticated:
        return redirect('home')
        
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    
    # Recuperiamo le ultime 50 attività
    # Ordiniamo per data decrescente per prendere le ultime, poi invertiamo per l'ordine cronologico nel grafico
    qs = Attivita.objects.filter(atleta=profilo).order_by('-data')[:50]
    attivita_list = list(reversed(qs))
    
    labels = []
    data_vo2 = []
    data_fc = []
    
    for act in attivita_list:
        # Formattiamo la data es: 24/01
        labels.append(act.data.strftime("%d/%m"))
        # Gestiamo i None per evitare errori nel JS
        data_vo2.append(act.vo2max_stimato if act.vo2max_stimato else None)
        data_fc.append(act.fc_media if act.fc_media else None)
        
    context = {
        'labels': json.dumps(labels),
        'data_vo2': json.dumps(data_vo2),
        'data_fc': json.dumps(data_fc),
    }
    return render(request, 'atleti/grafici.html', context)

def elimina_attivita_anomale(request):
    """Cancella dal DB le attività con distanza > 200km (es. errori GPS o import errati)"""
    if request.user.is_authenticated:
        count, _ = Attivita.objects.filter(atleta__user=request.user, distanza__gt=200000).delete()
        print(f"DEBUG: Cancellate {count} attività anomale.", flush=True)
    return redirect('home')

def export_csv(request):
    """Esporta le attività dell'atleta in formato CSV"""
    if not request.user.is_authenticated:
        return redirect('home')
        
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    
    response = HttpResponse(
        content_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="attivita_barilla_monitor.csv"'},
    )

    writer = csv.writer(response)
    # Intestazione colonne
    writer.writerow(['Data', 'Tipo', 'Distanza (km)', 'Durata (min)', 'Passo (min/km)', 'FC Media', 'FC Max', 'Dislivello (m)', 'Potenza (W)', 'VO2max Stimato'])

    attivita_list = Attivita.objects.filter(atleta=profilo).order_by('-data')

    for act in attivita_list:
        writer.writerow([
            act.data.strftime("%d/%m/%Y"),
            act.tipo_attivita,
            round(act.distanza / 1000, 2),
            round(act.durata / 60, 2),
            act.passo_medio,
            act.fc_media,
            act.fc_max_sessione,
            act.dislivello,
            act.potenza_media,
            act.vo2max_stimato
        ])

    return response

def riepilogo_atleti(request):
    """Vista per la tabella comparativa di tutti gli atleti"""
    if not request.user.is_authenticated:
        return redirect('home')
    
    # Controllo permessi: Solo lo staff può vedere questa pagina
    if not request.user.is_staff:
        return redirect('home')
    
    # Aggiungiamo l'annotazione per l'ultima attività
    atleti = ProfiloAtleta.objects.select_related('user').exclude(user__username='mastra').annotate(
        ultima_corsa=Max('sessioni__data')
    ).order_by('-vo2max_stima_statistica')
    
    return render(request, 'atleti/riepilogo_atleti.html', {'atleti': atleti})

def gare_atleta(request):
    """Visualizza solo le attività taggate come Gara su Strava"""
    if not request.user.is_authenticated:
        return redirect('home')
    
    profilo = request.user.profiloatleta
    # Strava workout_type: 1 = Race (Gara)
    gare = Attivita.objects.filter(atleta=profilo, workout_type=1).order_by('-data')
    
    return render(request, 'atleti/gare.html', {'gare': gare})

def _get_coach_dashboard_context(week_offset):
    """Helper per calcolare i dati della dashboard coach per una specifica settimana"""
    today = timezone.now()
    current_week_start = today - timedelta(days=today.weekday())
    current_week_start = current_week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    target_week_start = current_week_start + timedelta(weeks=week_offset)
    target_week_end = target_week_start + timedelta(weeks=1)
    prev_week_start = target_week_start - timedelta(weeks=1)

    # 1. Distribuzione VO2max (Pie Chart)
    vo2_ranges = {
        'Elite (>65)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_stima_statistica__gte=65).count(),
        'Eccellente (58-65)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_stima_statistica__gte=58, vo2max_stima_statistica__lt=65).count(),
        'Ottimo (52-58)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_stima_statistica__gte=52, vo2max_stima_statistica__lt=58).count(),
        'Buono (45-52)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_stima_statistica__gte=45, vo2max_stima_statistica__lt=52).count(),
        'Base (<45)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_stima_statistica__lt=45).count(),
    }
    print(f"DEBUG COACH - VO2 Ranges: {vo2_ranges}", flush=True)

    # 1c. Distribuzione VO2max Solo Strada
    vo2_strada_ranges = {
        'Elite (>65)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_strada__gte=65).count(),
        'Eccellente (58-65)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_strada__gte=58, vo2max_strada__lt=65).count(),
        'Ottimo (52-58)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_strada__gte=52, vo2max_strada__lt=58).count(),
        'Buono (45-52)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_strada__gte=45, vo2max_strada__lt=52).count(),
        'Base (<45)': ProfiloAtleta.objects.exclude(user__username='mastra').filter(vo2max_strada__lt=45).count(),
    }
    print(f"DEBUG COACH - VO2 Strada Ranges: {vo2_strada_ranges}", flush=True)
    
    # 1b. Distribuzione Strada vs Trail (Ultimi 90 giorni rispetto alla settimana visualizzata)
    last_90_days = target_week_end - timedelta(days=90)
    trail_count = Attivita.objects.exclude(atleta__user__username='mastra').filter(data__gte=last_90_days, data__lte=target_week_end, tipo_attivita='TrailRun').count()
    road_count = Attivita.objects.exclude(atleta__user__username='mastra').filter(data__gte=last_90_days, data__lte=target_week_end, tipo_attivita='Run').count()
    print(f"DEBUG COACH - Trail: {trail_count}, Road: {road_count}", flush=True)

    # 2. Atleti Inattivi (> 7 giorni)
    check_date = target_week_end
    seven_days_before_check = check_date - timedelta(days=7)
    
    # Subquery per trovare l'ultima attività rispetto alla data visualizzata
    last_activity_subquery = Attivita.objects.filter(
        atleta=OuterRef('pk'),
        data__lt=check_date
    ).order_by('-data').values('data')[:1]

    atleti_inattivi = ProfiloAtleta.objects.exclude(user__username='mastra').annotate(
        last_act=Subquery(last_activity_subquery)
    ).filter(Q(last_act__lt=seven_days_before_check) | Q(last_act__isnull=True)).order_by('last_act')

    # 3. Volume Settimanale Squadra (Trend)
    vol_current = Attivita.objects.exclude(atleta__user__username='mastra').filter(data__gte=target_week_start, data__lt=target_week_end).aggregate(Sum('distanza'))['distanza__sum'] or 0
    vol_prev = Attivita.objects.exclude(atleta__user__username='mastra').filter(data__gte=prev_week_start, data__lt=target_week_start).aggregate(Sum('distanza'))['distanza__sum'] or 0
    
    vol_current_km = round(vol_current / 1000, 1)
    vol_prev_km = round(vol_prev / 1000, 1)
    
    trend_vol = 0
    if vol_prev_km > 0:
        trend_vol = round(((vol_current_km - vol_prev_km) / vol_prev_km) * 100, 1)

    # 5. Top Ranking (ITRA & UTMB)
    top_itra = ProfiloAtleta.objects.exclude(user__username='mastra').filter(indice_itra__gt=0).select_related('user').order_by('-indice_itra')[:5]
    top_utmb = ProfiloAtleta.objects.exclude(user__username='mastra').filter(indice_utmb__gt=0).select_related('user').order_by('-indice_utmb')[:5]
    
    # Definiamo all_atleti qui, prima di usarlo nei cicli successivi
    all_atleti = ProfiloAtleta.objects.select_related('user').exclude(user__username='mastra').all()

    # 9. Top Power (W)
    atleti_power = []
    for a in all_atleti:
        # Calcoliamo la potenza media recente (ultime 30 attività)
        qs_p = Attivita.objects.filter(atleta=a).order_by('-data')[:30]
        p_vals = [act.potenza_media for act in qs_p if act.potenza_media and act.potenza_media > 0]
        avg_p = int(sum(p_vals) / len(p_vals)) if p_vals else 0
        if avg_p > 0:
            atleti_power.append({'atleta': a, 'power': avg_p})
    
    top_power = sorted(atleti_power, key=lambda x: x['power'], reverse=True)[:5]

    # 4. Analisi Trend Atleti (Top Improvers)
    atleti_trends = []
    
    for a in all_atleti:
        trends = calcola_trend_atleta(a, cutoff_date=target_week_end)
        if trends:
            atleti_trends.append({'atleta': a, 'trends': trends})
    
    # Ordiniamo per miglioramento VO2max
    top_improvers = sorted([x for x in atleti_trends if x['trends'].get('vo2max', 0) > 0], key=lambda x: x['trends'].get('vo2max', 0), reverse=True)[:5]
    # Ordiniamo per chi sta peggiorando (trend negativo)
    struggling = sorted([x for x in atleti_trends if x['trends'].get('vo2max', 0) < 0], key=lambda x: x['trends'].get('vo2max', 0))[:5]
    
    # 6. Allarmi FC (Aumento > 5% della FC Media = Possibile Fatica/Overreaching)
    fc_alerts = sorted([x for x in atleti_trends if x['trends'].get('fc_media', 0) > 5], key=lambda x: x['trends'].get('fc_media', 0), reverse=True)

    # 7. Allarmi Efficienza (Crollo VO2max > 3% = Possibile Malattia/Stress)
    vo2_alerts = sorted([x for x in atleti_trends if x['trends'].get('vo2max', 0) < -3.0], key=lambda x: x['trends'].get('vo2max', 0))

    # 8. Race Readiness (Potenziale Gara)
    readiness_buckets = {
        'Ultra Marathon 🏔️': [],
        'Marathon / 30k 🏃': [],
        'Half Marathon 🏁': [],
        '10k 👟': [],
        '5k / Base 👶': [],
        'Non Classificato': [],
    }
    for a in all_atleti:
        potenziale = stima_potenziale_gara(a)
        if potenziale in readiness_buckets:
            readiness_buckets[potenziale].append(a)
            
    # Calcolo percentuali
    readiness = {}
    total_count = all_atleti.count()
    
    for category, athletes in readiness_buckets.items():
        count = len(athletes)
        percentage = round((count / total_count * 100), 1) if total_count > 0 else 0
        readiness[category] = {
            'athletes': athletes,
            'percentage': percentage
        }

    # Calcolo percentuale inattivi
    perc_inattivi = 0
    if all_atleti.count() > 0:
        perc_inattivi = round((atleti_inattivi.count() / all_atleti.count()) * 100, 1)

    return {
        'vo2_labels': json.dumps(list(vo2_ranges.keys())),
        'vo2_data': json.dumps(list(vo2_ranges.values())),
        'vo2_strada_data': json.dumps(list(vo2_strada_ranges.values())),
        'trail_road_data': json.dumps([road_count, trail_count]),
        'top_itra': top_itra,
        'top_utmb': top_utmb,
        'top_power': top_power,
        'perc_inattivi': perc_inattivi,
        'atleti_inattivi': atleti_inattivi,
        'vol_current_km': vol_current_km,
        'vol_prev_km': vol_prev_km,
        'trend_vol': trend_vol,
        'top_improvers': top_improvers,
        'struggling': struggling,
        'fc_alerts': fc_alerts,
        'vo2_alerts': vo2_alerts,
        'readiness': readiness,
        'week_offset': week_offset,
        'week_label': f"Dal {target_week_start.strftime('%d/%m')} al {target_week_end.strftime('%d/%m')}",
        'prev_offset': week_offset - 1,
        'next_offset': week_offset + 1,
        'total_athletes': all_atleti.count()
    }

def dashboard_coach(request):
    """Dashboard generale per il coach: stato squadra, trend e inattività"""
    if not request.user.is_staff:
        return redirect('home')

    # Gestione navigazione settimane
    try:
        week_offset = int(request.GET.get('week', 0))
    except ValueError:
        week_offset = 0
    
    if week_offset > 0: week_offset = 0

    context = _get_coach_dashboard_context(week_offset)
    return render(request, 'atleti/dashboard_coach.html', context)

def analisi_coach_gemini(request):
    """API per generare l'analisi AI della dashboard corrente"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Non autorizzato'}, status=403)
    
    try:
        week_offset = int(request.GET.get('week', 0))
    except ValueError:
        week_offset = 0
        
    context = _get_coach_dashboard_context(week_offset)
    analisi_testo = analizza_squadra_coach(context)
    
    return JsonResponse({'analisi': analisi_testo})

def scheduler_logs(request):
    """Pagina per visualizzare i log dello schedulatore (Solo Staff)"""
    if not request.user.is_staff:
        return redirect('home')
    
    logs = DjangoJobExecution.objects.exclude(job__id='system_heartbeat').order_by('-run_time')[:50]
    jobs = DjangoJob.objects.exclude(id='system_heartbeat').order_by('next_run_time')
    
    # Recuperiamo i settings per vedere se c'è un trigger manuale attivo
    settings_map = {s.task_id: s for s in TaskSettings.objects.all()}
    # Creiamo una lista di tuple (id, nome, oggetto_setting)
    tasks_list = [(tid, name, settings_map.get(tid)) for tid, name in TaskSettings.TASK_CHOICES]
    
    # Controllo diagnostico: Se non ci sono job, lo scheduler non è partito o non ha inizializzato il DB
    if not jobs.exists():
        messages.warning(request, "⚠️ ATTENZIONE: Nessun Job trovato nel database. Assicurati che il container 'scheduler' sia avviato (docker compose up -d scheduler).")
    
    # Leggi il file di log raw (Console Output)
    log_content = ""
    log_path = '/code/scheduler.log'
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            # Leggi le ultime 200 righe per non intasare la pagina
            lines = f.readlines()
            log_content = "".join(lines[-200:])
    else:
        log_content = "File di log non ancora generato. Riavvia lo scheduler per crearlo."
        
    return render(request, 'atleti/scheduler_logs.html', {'logs': logs, 'jobs': jobs, 'tasks': tasks_list, 'now': timezone.now(), 'log_content': log_content})

def run_task_manually(request, task_id):
    """Richiede l'esecuzione manuale di un task impostando il flag nel DB"""
    if not request.user.is_staff:
        return redirect('home')
        
    # Imposta il flag manual_trigger
    setting, created = TaskSettings.objects.get_or_create(task_id=task_id)
    setting.manual_trigger = True
    setting.save()
    
    messages.success(request, f"Richiesta inviata per '{task_id}'. Lo scheduler lo eseguirà entro 10 secondi.")
    return redirect('scheduler_logs')

def scheduler_logs_update(request):
    """API per aggiornare i log via AJAX senza ricaricare la pagina"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 1. Log Console
    log_content = ""
    log_path = '/code/scheduler.log'
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            lines = f.readlines()
            log_content = "".join(lines[-200:])
    else:
        log_content = "File di log non ancora generato..."

    # 2. Storico Esecuzioni
    logs = DjangoJobExecution.objects.exclude(job__id='system_heartbeat').order_by('-run_time')[:50]
    
    # 3. Stato Job
    jobs = DjangoJob.objects.exclude(id='system_heartbeat').order_by('next_run_time')
    
    # 4. Task Settings (per aggiornare lo stato dei bottoni)
    settings_map = {s.task_id: s.manual_trigger for s in TaskSettings.objects.all()}
    
    # Renderizziamo i frammenti HTML
    logs_html = render_to_string('atleti/partials/logs_table_body.html', {'logs': logs})
    jobs_html = render_to_string('atleti/partials/jobs_table_body.html', {'jobs': jobs, 'now': timezone.now()})
    
    return JsonResponse({
        'log_content': log_content,
        'logs_html': logs_html,
        'jobs_html': jobs_html,
        'manual_triggers': settings_map
    })

def reset_task_trigger(request, task_id):
    """Annulla il flag di esecuzione manuale per un task bloccato"""
    if not request.user.is_staff:
        return redirect('home')
        
    try:
        setting = TaskSettings.objects.get(task_id=task_id)
        setting.manual_trigger = False
        setting.save()
        
        # Scriviamo direttamente nel file di log dello scheduler per feedback immediato nella dashboard
        log_path = '/code/scheduler.log'
        if os.path.exists(log_path):
            with open(log_path, 'a') as f:
                timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp} [INFO] WEB: Trigger per '{task_id}' ANNULLATO da {request.user.username}\n")
        
        messages.info(request, f"Trigger per '{task_id}' annullato manualmente.")
    except TaskSettings.DoesNotExist:
        pass
    
    return redirect('scheduler_logs')
