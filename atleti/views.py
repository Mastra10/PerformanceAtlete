import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from allauth.socialaccount.models import SocialToken ,SocialAccount
from django.core.cache import cache
from .models import Attivita, ProfiloAtleta, LogSistema, Scarpa
import math
from .utils import analizza_performance_atleta, calcola_metrica_vo2max, stima_vo2max_atleta, stima_potenza_watt, calcola_trend_atleta, formatta_passo, stima_potenziale_gara, analizza_squadra_coach, calcola_vam_selettiva, refresh_strava_token, processa_attivita_strava, fix_strava_duplicates, normalizza_scarpa, BRAND_LOGOS, analizza_gare_atleta
import time
from django.db.models import Sum, Max, Q, OuterRef, Subquery, Avg
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
from django.contrib.auth import login
import os
from django.core.exceptions import MultipleObjectsReturned
from django.utils.safestring import mark_safe

def _get_dashboard_context(user):
    """Helper per generare il contesto della dashboard per un dato utente"""
        # Recuperiamo il profilo
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=user)
        
        # 1. Calcolo KM Totali (da metri a km)
    metri = Attivita.objects.filter(atleta=profilo).aggregate(Sum('distanza'))['distanza__sum'] or 0
    totale_km = round(metri / 1000, 1)
        
    # 1b. Calcolo Dislivello Totale
    dislivello_totale = Attivita.objects.filter(atleta=profilo).aggregate(Sum('dislivello'))['dislivello__sum'] or 0
    
    # 1c. Calcolo Dislivello Settimanale (Lun-Dom)
    today = timezone.now()
    start_week = today - timedelta(days=today.weekday())
    start_week = start_week.replace(hour=0, minute=0, second=0, microsecond=0)
    dislivello_settimanale = Attivita.objects.filter(atleta=profilo, data__gte=start_week).aggregate(Sum('dislivello'))['dislivello__sum'] or 0

    # 1d. Calcolo Volume Annuale (Anno Corrente)
    start_year = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    qs_anno = Attivita.objects.filter(atleta=profilo, data__gte=start_year)
    annuale_metri = qs_anno.aggregate(Sum('distanza'))['distanza__sum'] or 0
    annuale_km = round(annuale_metri / 1000, 1)
    dislivello_annuale = qs_anno.aggregate(Sum('dislivello'))['dislivello__sum'] or 0
    
    # Calcolo medie settimanali anno corrente
    current_week = today.isocalendar()[1]
    avg_weekly_km = round(annuale_km / max(1, current_week), 1)
    avg_weekly_elev = int(dislivello_annuale / max(1, current_week))

        # 2. Recupero le ultime 30 attività per la tabella
    attivita_list = Attivita.objects.filter(atleta=profilo).order_by('-data')[:30]
        
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

    # Warning Token Strava Scaduto
    warning_token = None
    token_obj = SocialToken.objects.filter(account__user=user, account__provider='strava').first()
    if token_obj and token_obj.expires_at and token_obj.expires_at < timezone.now():
        warning_token = "⚠️ Il tuo token Strava è scaduto. Prova a sincronizzare. Se fallisce, scollega e ricollega l'account nelle Impostazioni."

    return {
        'totale_km': totale_km,
        'dislivello_totale': int(dislivello_totale),
        'dislivello_settimanale': int(dislivello_settimanale),
        'annuale_km': annuale_km,
        'dislivello_annuale': int(dislivello_annuale),
        'avg_weekly_km': avg_weekly_km,
        'avg_weekly_elev': avg_weekly_elev,
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
        'warning_token': warning_token,
    }

# 1. Questa mostra la pagina (NON cancellarla!)
def home(request):
    # Fix preventivo per crash allauth su app duplicate
    fix_strava_duplicates()

    # Endpoint per polling stato sync (chiamato via AJAX dal modal)
    if request.GET.get('sync_status'):
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'Login richiesto', 'progress': 0}, status=401)
            
        status = cache.get(f"sync_progress_{request.user.id}", {'status': 'In attesa...', 'progress': 0})
        return JsonResponse(status)

    try:
        if request.user.is_authenticated:
            LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Dashboard")
            context = _get_dashboard_context(request.user)
            if context.get('warning_token'):
                messages.warning(request, context['warning_token'])
            # Link temporaneo per rendere visibile la nuova pagina
            messages.info(request, mark_safe('📊 <strong>Novità:</strong> Prova il nuovo strumento di <a href="/confronto/" class="alert-link">Confronto Atleti</a>!'))
            
            # Avviso in evidenza per aggiornamento permessi scarpe
            messages.warning(request, mark_safe(
                '<h5>👟 Nuove Funzionalità Disponibili!</h5>'
                '<p class="mb-2">Per scaricare le tue <strong>Scarpe</strong> e l\'attrezzatura, è necessario aggiornare i permessi di collegamento.</p>'
                '<a href="/impostazioni/" class="btn btn-sm btn-outline-dark">Vai a Impostazioni > Scollega e Ricollega Strava</a>'
            ))
            return render(request, 'atleti/home.html', context)
        return render(request, 'atleti/home.html')
    except MultipleObjectsReturned:
        # Se il fix preventivo non ha funzionato (es. race condition), riproviamo e ricarichiamo
        print("CRITICAL: MultipleObjectsReturned intercettato in home. Tento fix di emergenza.", flush=True)
        fix_strava_duplicates()
        return redirect('home')

def dashboard_atleta(request, username):
    """Visualizza la dashboard di un altro atleta se permesso"""
    if request.user.is_authenticated:
        LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio=f"Visita Dashboard di {username}")

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
    # Supporto per chiamata AJAX da Modal
    is_api = request.GET.get('api') == 'true'
    
    # Supporto per admin che analizza un altro atleta
    target_username = request.GET.get('username')
    if target_username and (request.user.is_staff or request.user.username == target_username):
        target_user = get_object_or_404(User, username=target_username)
        profilo = target_user.profiloatleta
    else:
        profilo = request.user.profiloatleta

    if is_api:
        LogSistema.objects.create(livello='INFO', azione='Analisi AI', utente=request.user, messaggio=f"Richiesta analisi personale per {profilo.user.username}")

    commento_ai = analizza_performance_atleta(profilo)
    profilo.ultima_analisi_ai = commento_ai
    profilo.save()
    
    if is_api:
        return JsonResponse({'analisi': commento_ai})
        
    return render(request, 'atleti/home.html', {'analisi': commento_ai})


def calcola_vo2max(request):
    if request.method == 'POST':
        LogSistema.objects.create(livello='INFO', azione='Analisi AI', utente=request.user, messaggio="Richiesta analisi performance avviata.")
        profilo = request.user.profiloatleta
        hr_rest = request.POST.get('hr_rest')
        
        if hr_rest:
            profilo.fc_riposo = int(hr_rest) # Corretto nome campo
            profilo.save()

            # Chiamata a Gemini
            try:
                analisi_testo = analizza_performance_atleta(profilo)
                
                if analisi_testo:
                    profilo.ultima_analisi_ai = analisi_testo
                    profilo.save()
                    LogSistema.objects.create(livello='INFO', azione='Analisi AI', utente=request.user, messaggio="Analisi completata e salvata.")
                else:
                    LogSistema.objects.create(livello='WARNING', azione='Analisi AI', utente=request.user, messaggio="Gemini ha restituito risposta vuota.")
            except Exception as e:
                LogSistema.objects.create(livello='ERROR', azione='Analisi AI', utente=request.user, messaggio=f"Errore: {e}")
        else:
            LogSistema.objects.create(livello='WARNING', azione='Analisi AI', utente=request.user, messaggio="HR Rest mancante nel form.")
            
    return redirect('home')

def impostazioni(request):
    if request.method == 'GET' and request.user.is_authenticated:
        LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Impostazioni")

    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    strava_connected = SocialAccount.objects.filter(user=request.user, provider='strava').exists()

    if request.method == 'POST':
        # Gestione Disconnessione Strava (per aggiornare permessi o cambiare account)
        if 'disconnect_strava' in request.POST:
            SocialToken.objects.filter(account__user=request.user, account__provider='strava').delete()
            SocialAccount.objects.filter(user=request.user, provider='strava').delete()
            LogSistema.objects.create(livello='WARNING', azione='Disconnessione', utente=request.user, messaggio="Account Strava scollegato.")
            messages.success(request, "Account Strava scollegato. Ricollegalo per aggiornare i permessi.")
            return redirect('impostazioni')

        try:
            peso = float(request.POST.get('peso'))
            fc_riposo = int(request.POST.get('fc_riposo'))
            fc_max = int(request.POST.get('fc_max'))
            
            # Nuovi campi impostazioni
            mostra_peso = request.POST.get('mostra_peso') == 'on'
            dashboard_pubblica = request.POST.get('dashboard_pubblica') == 'on'
            indice_itra = int(request.POST.get('indice_itra') or 0)
            indice_utmb = int(request.POST.get('indice_utmb') or 0)
            importa_attivita_private = request.POST.get('importa_attivita_private') == 'on'
            condividi_metriche = request.POST.get('condividi_metriche') == 'on'
            
            profilo.peso = peso
            profilo.mostra_peso = mostra_peso
            profilo.peso_manuale = request.POST.get('peso_manuale') == 'on'
            profilo.dashboard_pubblica = dashboard_pubblica
            profilo.importa_attivita_private = importa_attivita_private
            profilo.condividi_metriche = condividi_metriche
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
    return render(request, 'atleti/impostazioni.html', {'profilo': profilo, 'strava_connected': strava_connected})

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
def hide_home_notice(request):
    """Endpoint AJAX per salvare la preferenza di non mostrare più l'avviso nella home."""
    if request.method == 'POST':
        try:
            profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
            # Accettiamo sia JSON che form-encoded
            # Se client invia {'hide': true} -> impostiamo a True
            hide = request.POST.get('hide')
            if hide is None:
                try:
                    data = json.loads(request.body.decode('utf-8') or '{}')
                    hide = data.get('hide')
                except Exception:
                    hide = None

            if isinstance(hide, str):
                hide = hide.lower() in ('1', 'true', 'on')

            if hide is None:
                return JsonResponse({'error': 'Parametro mancante'}, status=400)

            profilo.hide_home_notice = bool(hide)
            profilo.save()
            return JsonResponse({'ok': True, 'hide': profilo.hide_home_notice})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Metodo non permesso'}, status=405)

@login_required
def sincronizza_strava(request):
    LogSistema.objects.create(livello='INFO', azione='Sync Manuale', utente=request.user, messaggio="Avvio sincronizzazione...")
    cache_key = f"sync_progress_{request.user.id}"
    cache.set(cache_key, {'status': 'Connessione a Strava...', 'progress': 5}, timeout=300)
    
    social_acc = SocialAccount.objects.filter(user=request.user, provider='strava').first()
    if not social_acc:
        LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="SocialAccount non trovato.")
        messages.error(request, "Nessun account Strava collegato. Vai nelle impostazioni.")
        return redirect('home')

    token_obj = SocialToken.objects.filter(account=social_acc).first()
    if not token_obj:
        LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="SocialToken non trovato.")
        messages.error(request, "Token Strava mancante o scaduto. Prova a scollegare e ricollegare l'account.")
        return redirect('home')

    
    # 1. Refresh Token (Nuova logica centralizzata)
    access_token = refresh_strava_token(token_obj)
    if not access_token:
        LogSistema.objects.create(livello='ERROR', azione='Sync Manuale', utente=request.user, messaggio="Refresh token fallito.")
        messages.error(request, "Il token Strava è scaduto e non può essere rinnovato. Per favore scollega e ricollega l'account nelle Impostazioni.")
        return redirect('impostazioni')
        
    headers = {'Authorization': f'Bearer {access_token}'}

    cache.set(cache_key, {'status': 'Aggiornamento profilo...', 'progress': 10}, timeout=300)
    # --- 2. DATI PROFILO (PESO E NOMI) ---
    athlete_res = requests.get("https://www.strava.com/api/v3/athlete", headers=headers)
    
    if athlete_res.status_code == 401:
        LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="Token scaduto durante fetch profilo.")
        return redirect('/accounts/strava/login/')

    # Aggiorniamo il profilo atleta
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)

    # Recuperiamo il peso dai dati di login (extra_data) che spesso sono più completi dell'API limitata
    if social_acc.extra_data and social_acc.extra_data.get('weight'):
        weight_extra = social_acc.extra_data.get('weight')
        if not profilo.peso_manuale:
            profilo.peso = weight_extra
        else:
            pass
        
        # Recuperiamo immagine da SocialAccount come fallback/init
        img_extra = social_acc.extra_data.get('profile')
        if img_extra:
            profilo.immagine_profilo = img_extra

    if athlete_res.status_code == 200:
        athlete_data = athlete_res.json()
        # DEBUG: Verifichiamo se Strava ci manda le scarpe
        print(f"DEBUG STRAVA: Trovate {len(athlete_data.get('shoes', []))} scarpe nel profilo.", flush=True)

        # Aggiorniamo il peso SOLO se Strava ce lo fornisce (evita sovrascrittura con 70kg)
        strava_weight = athlete_data.get('weight')
        if strava_weight and not profilo.peso_manuale:
            profilo.peso = strava_weight
        
        # Aggiorniamo immagine profilo dall'API (più recente)
        strava_img = athlete_data.get('profile')
        if strava_img:
            profilo.immagine_profilo = strava_img
            
        request.user.first_name = athlete_data.get('firstname', '')
        request.user.last_name = athlete_data.get('lastname', '')
        request.user.save()
        
        # --- SYNC SCARPE ---
        shoes = athlete_data.get('shoes', [])
        strava_shoe_ids = []
        for s in shoes:
            strava_shoe_ids.append(s['id'])
            brand, model = normalizza_scarpa(s['name'])
            Scarpa.objects.update_or_create(
                strava_id=s['id'],
                defaults={
                    'atleta': profilo,
                    'nome': s['name'],
                    'distanza': s['distance'],
                    'primary': s['primary'],
                    'brand': brand,
                    'modello_normalizzato': model,
                    'retired': False # Se è nella lista, è attiva
                }
            )
        
        # Le scarpe che abbiamo nel DB ma non sono più nella lista di Strava sono considerate "Dismesse"
        Scarpa.objects.filter(atleta=profilo).exclude(strava_id__in=strava_shoe_ids).update(retired=True)
    profilo.save()

    # --- CHECK BLOCCANTE: Se mancano Peso o FC Riposo, STOP ---
    if not profilo.peso or not profilo.fc_riposo:
        LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="Dati profilo (Peso/FC) mancanti.")
        return redirect('impostazioni')

    # --- 4. SCARICAMENTO ATTIVITÀ (FULL SYNC + CHECKPOINT) ---
    # Cerchiamo l'ultima attività salvata per usare il parametro 'after' (Checkpoint)
    last_activity = Attivita.objects.filter(atleta=profilo).order_by('-data').first()
    timestamp_checkpoint = None
    
    if last_activity:
        # Aggiungiamo 1 secondo per non riscaricare l'ultima attività
        timestamp_checkpoint = int(last_activity.data.timestamp()) + 1
    else:
        LogSistema.objects.create(livello='INFO', azione='Sync Manuale', utente=request.user, messaggio="Primo download completo.")

    url_activities = "https://www.strava.com/api/v3/athlete/activities"
    
    page = 1
    per_page = 100 # Ottimizzazione: scarichiamo blocchi più grandi (max supportato ~200)
    
    while True:
        params = {'page': page, 'per_page': per_page}
        cache.set(cache_key, {'status': f'Scaricamento attività (Pagina {page})...', 'progress': min(15 + (page * 10), 80)}, timeout=300)
        if timestamp_checkpoint:
            params['after'] = timestamp_checkpoint
            
        response = requests.get(url_activities, headers=headers, params=params)
        

        if response.status_code == 401:
            # TENTATIVO DI RECOVERY: Il token potrebbe essere revocato o scaduto nonostante il DB dica il contrario.
            # Tentiamo un refresh forzato e riproviamo.
            new_token = refresh_strava_token(token_obj, force=True)
            if new_token:
                headers = {'Authorization': f'Bearer {new_token}'}
                response = requests.get(url_activities, headers=headers, params=params)
            
            if response.status_code == 401:
                LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="Token scaduto/revocato anche dopo refresh. Login richiesto.")
                return redirect('/accounts/strava/login/')

        if response.status_code == 429:
            LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="Rate Limit Strava raggiunto.")
            break

        if response.status_code != 200:
            LogSistema.objects.create(livello='ERROR', azione='Sync Manuale', utente=request.user, messaggio=f"Errore API: {response.text}")
            break
            
        activities = response.json()
        if not activities:
            break
            

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
        else:
            pass

    # --- 9. CALCOLO VO2MAX CONSOLIDATO (MEDIA MOBILE) ---
    profilo.data_ultima_sincronizzazione = timezone.now()
    stima_vo2max_atleta(profilo)

    cache.set(cache_key, {'status': 'Completato!', 'progress': 100}, timeout=300)
    LogSistema.objects.create(livello='INFO', azione='Sync Manuale', utente=request.user, messaggio="Sincronizzazione completata con successo.")
    return redirect('home')

@login_required
def ricalcola_statistiche(request):
    """Ricalcola manualmente le statistiche (VO2max, ecc) per l'utente corrente"""
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    
    # 1. Ricalcola VO2max per ogni singola attività
    attivita = Attivita.objects.filter(atleta=profilo)
    count = 0
    cleaned_count = 0
    for act in attivita:
        if act.distanza > 0 and act.durata > 0:
            nuovo_vo2 = calcola_metrica_vo2max(act, profilo)
            # Aggiorniamo anche se è None (per rimuovere valori vecchi non più validi per passo lento)
            if act.vo2max_stimato != nuovo_vo2:
                if nuovo_vo2 is None:
                    cleaned_count += 1
                act.vo2max_stimato = nuovo_vo2
                act.save()
                count += 1

    # 2. Aggiorna i campi aggregati del profilo
    profilo.data_ultimo_ricalcolo_statistiche = timezone.now()
    stima_vo2max_atleta(profilo)
    profilo.save()
    
    LogSistema.objects.create(livello='INFO', azione='Ricalcolo Stats', utente=request.user, messaggio=f"Ricalcolate {count} attività.")
    messages.success(request, f"Statistiche aggiornate: {count} ricalcolate (di cui {cleaned_count} rimosse per passo lento).")
    return redirect('home')

def grafici_atleta(request):
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.has_perm('atleti.access_grafici')):
        messages.error(request, "Non hai i permessi per visualizzare i Grafici.")
        return redirect('home')
        
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Grafici")
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    
    # Recuperiamo le ultime 50 attività
    # Ordiniamo per data decrescente per prendere le ultime, poi invertiamo per l'ordine cronologico nel grafico
    qs = Attivita.objects.filter(atleta=profilo).order_by('-data')[:50]
    attivita_list = list(reversed(qs))
    
    labels = []
    data_vo2 = []
    data_vo2_strada = []
    data_fc = []
    data_dist = []
    data_elev = []
    data_power = []
    data_vam = []
    data_pace = []
    
    for act in attivita_list:
        # Formattiamo la data es: 24/01
        labels.append(act.data.strftime("%d/%m"))
        
        # VO2max Totale
        data_vo2.append(act.vo2max_stimato if act.vo2max_stimato else None)
        
        # VO2max Solo Strada (Solo se Run)
        if act.tipo_attivita == 'Run' and act.vo2max_stimato:
            data_vo2_strada.append(act.vo2max_stimato)
        else:
            data_vo2_strada.append(None)

        # Altre metriche
        data_fc.append(act.fc_media if act.fc_media else None)
        data_dist.append(round(act.distanza / 1000, 2))
        data_elev.append(act.dislivello)
        data_power.append(act.potenza_media if act.potenza_media else None)
        data_vam.append(act.vam) # Usa la property del model
        
        # Passo (min/km decimali)
        if act.distanza > 0:
            pace_min = (act.durata / 60) / (act.distanza / 1000)
            data_pace.append(round(pace_min, 2))
        else:
            data_pace.append(None)
        
    context = {
        'labels': json.dumps(labels),
        'data_vo2': json.dumps(data_vo2),
        'data_vo2_strada': json.dumps(data_vo2_strada),
        'data_fc': json.dumps(data_fc),
        'data_dist': json.dumps(data_dist),
        'data_elev': json.dumps(data_elev),
        'data_power': json.dumps(data_power),
        'data_vam': json.dumps(data_vam),
        'data_pace': json.dumps(data_pace),
    }
    return render(request, 'atleti/grafici.html', context)

def elimina_attivita_anomale(request):
    """Cancella dal DB le attività con distanza > 200km (es. errori GPS o import errati)"""
    if request.user.is_authenticated:
        count, _ = Attivita.objects.filter(atleta__user=request.user, distanza__gt=200000).delete()
        LogSistema.objects.create(livello='INFO', azione='Pulizia DB', utente=request.user, messaggio=f"Cancellate {count} attività anomale (>200km).")
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

def export_profile_csv(request):
    """Esporta i dati aggregati del profilo in CSV (Dashboard Stats)"""
    if not request.user.is_authenticated:
        return redirect('home')

    context = _get_dashboard_context(request.user)
    profilo = context['profilo']
    trends = context['trends']

    response = HttpResponse(
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="profilo_{request.user.username}.csv"'},
    )

    writer = csv.writer(response)
    writer.writerow(['Metrica', 'Valore', 'Note/Trend'])

    writer.writerow(['Peso', f"{profilo.peso} kg", ''])
    writer.writerow(['FC Max', f"{profilo.fc_massima_teorica} bpm", f"Data: {profilo.data_fc_max or 'N/A'}"])
    writer.writerow(['ITRA Index', profilo.indice_itra, context['livello_itra']])
    writer.writerow(['UTMB Index', profilo.indice_utmb, context['livello_utmb']])
    writer.writerow(['Soglia Aerobica', f"{context['soglia_aerobica']} bpm", 'Stima Fondo (Z2)'])
    writer.writerow(['Soglia Anaerobica', f"{context['soglia_anaerobica']} bpm", 'Stima Soglia (Z4)'])
    writer.writerow(['Passo Medio Recente', context['passo_media_recent'], f"Trend: {trends.get('passo', 0)}%"])
    writer.writerow(['FC Media Recente', f"{context['fc_media_recent']} bpm", f"Trend: {trends.get('fc_media', 0)}%"])
    
    writer.writerow(['Volume Totale', f"{context['totale_km']} km", f"{context['dislivello_totale']}m D+"])
    writer.writerow(['Dislivello Settimanale', f"{context['dislivello_settimanale']}m D+", ''])
    writer.writerow(['Trend Volume', f"{trends.get('distanza', 0)}%", 'Vol. Recente'])
    
    writer.writerow(['Volume Anno', f"{context['annuale_km']} km", f"{context['dislivello_annuale']}m D+"])
    writer.writerow(['Media Settimanale', f"{context['avg_weekly_km']} km / {context['avg_weekly_elev']} m", ''])
    
    writer.writerow(['VAM Media', f"{context['vam_media']} m/h", f"{context['livello_vam']} (Trend: {trends.get('vam', 0)}%)"])
    writer.writerow(['Potenza Media', f"{context['potenza_media']} W", f"{context['livello_potenza']} (Trend: {trends.get('potenza', 0)}%)"])
    
    writer.writerow(['VO2max Stima Statistica', profilo.vo2max_stima_statistica, f"{context['livello_vo2max']} (Trend: {trends.get('vo2max', 0)}%)"])
    writer.writerow(['VO2max Solo Strada', profilo.vo2max_strada, f"{context['livello_vo2max_strada']} (Trend: {trends.get('vo2max_strada', 0)}%)"])

    return response

def riepilogo_atleti(request):
    """Vista per la tabella comparativa di tutti gli atleti"""
    if not request.user.is_authenticated:
        return redirect('home')
    
    # Controllo permessi: Staff o Permesso Esplicito
    if not (request.user.is_staff or request.user.has_perm('atleti.access_riepilogo')):
        messages.error(request, "Non hai i permessi per visualizzare il Riepilogo Atleti.")
        return redirect('home')
    
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Riepilogo Atleti")
    # Aggiungiamo l'annotazione per l'ultima attività
    atleti = ProfiloAtleta.objects.select_related('user').exclude(user__username='mastra').annotate(
        ultima_corsa=Max('sessioni__data')
    ).order_by('-vo2max_stima_statistica')
    
    # Offuscamento dati sensibili per chi non vuole condividerli (tranne per Staff)
    if not request.user.is_staff:
        for atleta in atleti:
            if not atleta.condividi_metriche:
                # Sovrascriviamo i valori sull'oggetto in memoria (non nel DB)
                atleta.vo2max_stima_statistica = None # Apparirà come "None" o vuoto nel template
                atleta.vo2max_strada = None
                atleta.indice_itra = 0
                atleta.indice_utmb = 0
    
    return render(request, 'atleti/riepilogo_atleti.html', {'atleti': atleti})

def gare_atleta(request):
    """Visualizza solo le attività taggate come Gara su Strava"""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.has_perm('atleti.access_gare')):
        messages.error(request, "Non hai i permessi per visualizzare le Gare.")
        return redirect('home')
    
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Gare")
    profilo = request.user.profiloatleta
    
    # Gestione salvataggio piazzamento
    if request.method == 'POST':
        try:
            act_id = request.POST.get('activity_id')
            pos_str = request.POST.get('piazzamento')
            
            activity = get_object_or_404(Attivita, id=act_id, atleta=profilo)
            
            if pos_str and pos_str.strip():
                activity.piazzamento = int(pos_str)
                print(f"DEBUG: Salvataggio piazzamento {activity.piazzamento} per gara {activity.id}", flush=True)
            else:
                activity.piazzamento = None
                print(f"DEBUG: Rimozione piazzamento per gara {activity.id}", flush=True)
            activity.save()
            messages.success(request, f"Piazzamento aggiornato per {activity.nome}")
        except ValueError:
            messages.error(request, "Valore piazzamento non valido")
        return redirect('gare_atleta')

    # Strava workout_type: 1 = Race (Gara)
    gare = Attivita.objects.filter(atleta=profilo, workout_type=1).order_by('-data')
    
    # Calcolo Statistiche
    stats = {
        'count': gare.count(),
        'avg_km': 0,
        'avg_dplus': 0,
        'avg_pos': None,
        'total_km': 0,
    }
    
    if stats['count'] > 0:
        avg_dist = gare.aggregate(Avg('distanza'))['distanza__avg']
        stats['avg_km'] = round(avg_dist / 1000, 2) if avg_dist else 0
        
        total_dist = gare.aggregate(Sum('distanza'))['distanza__sum']
        stats['total_km'] = round(total_dist / 1000, 1) if total_dist else 0
        
        avg_elev = gare.aggregate(Avg('dislivello'))['dislivello__avg']
        stats['avg_dplus'] = int(avg_elev) if avg_elev else 0
        
        gare_con_pos = gare.filter(piazzamento__isnull=False)
        if gare_con_pos.exists():
            avg_pos = gare_con_pos.aggregate(Avg('piazzamento'))['piazzamento__avg']
            stats['avg_pos'] = round(avg_pos, 1)

    # Dati Grafico (Cronologico)
    gare_chrono = list(reversed(gare))
    chart_labels = [g.data.strftime('%d/%m/%y') for g in gare_chrono]
    chart_pos = [g.piazzamento if g.piazzamento else None for g in gare_chrono]
    chart_types = [g.tipo_attivita for g in gare_chrono]
    
    # Dati Grafico a Torta (Distribuzione Piazzamenti)
    pos_buckets = {
        'Top 10': 0,
        'Top 20': 0,
        'Top 30': 0,
        'Oltre 30': 0
    }
    
    gare_con_pos = gare.filter(piazzamento__isnull=False)
    for g in gare_con_pos:
        p = g.piazzamento
        if p <= 10: pos_buckets['Top 10'] += 1
        elif p <= 20: pos_buckets['Top 20'] += 1
        elif p <= 30: pos_buckets['Top 30'] += 1
        else: pos_buckets['Oltre 30'] += 1

    return render(request, 'atleti/gare.html', {
        'gare': gare,
        'stats': stats,
        'chart_labels': json.dumps(chart_labels),
        'chart_pos': json.dumps(chart_pos),
        'chart_types': json.dumps(chart_types),
        'pie_labels': json.dumps(list(pos_buckets.keys())),
        'pie_data': json.dumps(list(pos_buckets.values())),
        'has_races': gare.exists(), # Flag esplicito per mostrare i grafici
    })

def analisi_gare_ai(request):
    """API per generare l'analisi AI delle gare"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Non autorizzato'}, status=403)
        
    profilo = request.user.profiloatleta
    analisi_testo = analizza_gare_atleta(profilo)
    return JsonResponse({'analisi': analisi_testo})

def guida_utente(request):
    """Pagina di documentazione per gli utenti"""
    if request.user.is_authenticated:
        LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Guida Utente")
    return render(request, 'atleti/guida.html')

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

    # 7. Allarmi ACWR (Acute:Chronic Workload Ratio) - Sostituisce VO2max drop
    # Calcoliamo il carico basato sui "Km Sforzo" (1km + 100m D+)
    acwr_alerts = []
    
    # FIX: Per la settimana corrente (offset 0), calcoliamo ACWR su finestra mobile reale (fino a oggi)
    # per evitare falsi allarmi "Detraining" a inizio settimana.
    # Per lo storico, manteniamo il calcolo a fine settimana.
    acwr_ref_date = timezone.now() if week_offset == 0 else target_week_end

    for a in all_atleti:
        # Definiamo finestre temporali
        start_acute = acwr_ref_date - timedelta(days=7)
        start_chronic = acwr_ref_date - timedelta(days=28)
        
        # Recuperiamo attività degli ultimi 28gg
        qs_chronic = Attivita.objects.filter(atleta=a, data__gte=start_chronic, data__lt=acwr_ref_date)
        
        load_acute = 0
        load_chronic_total = 0
        
        for act in qs_chronic:
            km_flat = act.distanza / 1000
            km_vert = act.dislivello / 100
            load_val = km_flat + km_vert # Km Sforzo
            
            load_chronic_total += load_val
            if act.data >= start_acute:
                load_acute += load_val
        
        avg_chronic = load_chronic_total / 4
        
        # Analizziamo solo chi ha un volume minimo (>10 Km Sforzo/settimana)
        if avg_chronic > 10:
            ratio = load_acute / avg_chronic
            
            # Soglie: > 1.3 (Rischio Infortunio), < 0.6 (Detraining severo)
            if ratio >= 1.3 or ratio <= 0.6:
                status = "High Risk ⚠️" if ratio >= 1.3 else "Detraining 📉"
                acwr_alerts.append({'atleta': a, 'ratio': round(ratio, 2), 'status': status, 'acute': int(load_acute), 'chronic': int(avg_chronic)})
    
    # Ordiniamo per gravità (distanza da 1.0)
    acwr_alerts = sorted(acwr_alerts, key=lambda x: abs(x['ratio'] - 1.0), reverse=True)

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
        'acwr_alerts': acwr_alerts, # Nuova chiave
        'readiness': readiness,
        'week_offset': week_offset,
        'week_label': f"Dal {target_week_start.strftime('%d/%m')} al {target_week_end.strftime('%d/%m')}",
        'prev_offset': week_offset - 1,
        'next_offset': week_offset + 1,
        'total_athletes': all_atleti.count()
    }

def dashboard_coach(request):
    """Dashboard generale per il coach: stato squadra, trend e inattività"""
    if not (request.user.is_staff or request.user.has_perm('atleti.access_coach_dashboard')):
        messages.error(request, "Non hai i permessi per visualizzare la Dashboard Coach.")
        return redirect('home')

    # Gestione navigazione settimane
    try:
        week_offset = int(request.GET.get('week', 0))
    except ValueError:
        week_offset = 0
    
    if week_offset > 0: week_offset = 0

    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Dashboard Coach")
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
    
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Log Scheduler")
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
    
    # DEBUG: Conferma salvataggio su log applicativo
    print(f"WEB: Richiesta manuale per '{task_id}' salvata. Flag manual_trigger=True.", flush=True)
    LogSistema.objects.create(livello='INFO', azione='Task Manuale', utente=request.user, messaggio=f"Richiesto avvio manuale di {task_id}")
    
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
                timestamp = timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp} [INFO] WEB: Trigger per '{task_id}' ANNULLATO da {request.user.username}\n")
        
        messages.info(request, f"Trigger per '{task_id}' annullato manualmente.")
    except TaskSettings.DoesNotExist:
        pass
    
    return redirect('scheduler_logs')

@login_required
def impersonate_user(request, username):
    """Permette a un admin di loggarsi come un altro utente"""
    if not request.user.is_staff:
        messages.error(request, "Azione non autorizzata.")
        return redirect('home')
    
    original_admin = request.user.username
    target_user = get_object_or_404(User, username=username)
    
    # Effettua il login forzato come l'utente target
    # Usiamo il ModelBackend standard di Django
    login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')
    
    # Impostiamo un flag nella sessione del nuovo utente per ricordare chi sta impersonando
    request.session['impersonator'] = original_admin
    
    messages.warning(request, f"⚠️ ATTENZIONE: Ora stai agendo come {target_user.username}. Effettua il Logout per uscire.")
    return redirect('home')

def confronto_attivita(request):
    """
    Vista per confrontare due attività di due utenti diversi (o dello stesso).
    Gestisce sia la pagina principale che le chiamate AJAX per popolare le select.
    """
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.has_perm('atleti.access_confronto')):
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            messages.error(request, "Non hai i permessi per accedere al Confronto.")
        return redirect('home')

    # 1. Gestione AJAX: Restituisce le attività di un utente specifico
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.GET.get('ajax_user_id'):
        user_id = request.GET.get('ajax_user_id')
        try:
            profilo = ProfiloAtleta.objects.get(user_id=user_id)
            # Prendiamo tutte le attività (rimosso limite)
            attivita = Attivita.objects.filter(atleta=profilo).order_by('-data')[:60]
            data = []
            for a in attivita:
                label = f"{a.data.strftime('%d/%m/%Y')} - {a.nome or 'Attività'} ({round(a.distanza/1000, 1)}km, {a.dislivello}m D+)"
                data.append({'id': a.id, 'label': label})
            return JsonResponse({'activities': data})
        except ProfiloAtleta.DoesNotExist:
            return JsonResponse({'activities': []})

    # 2. Gestione Confronto (Se sono stati selezionati due ID)
    act1_id = request.GET.get('act1')
    act2_id = request.GET.get('act2')
    
    context = {}
    
    # Carichiamo tutti gli atleti per le select iniziali
    context['atleti'] = ProfiloAtleta.objects.select_related('user').all().order_by('user__first_name')

    if act1_id and act2_id:
        act1 = get_object_or_404(Attivita, id=act1_id)
        act2 = get_object_or_404(Attivita, id=act2_id)
        
        # Calcolo Delta (Act1 - Act2)
        delta = {
            'distanza': round((act1.distanza - act2.distanza) / 1000, 2),
            'dislivello': act1.dislivello - act2.dislivello,
            'fc_media': (act1.fc_media or 0) - (act2.fc_media or 0),
            'potenza': (act1.potenza_media or 0) - (act2.potenza_media or 0),
            'vo2': round((act1.vo2max_stimato or 0) - (act2.vo2max_stimato or 0), 1),
            'vam': act1.vam - act2.vam,
        }
        
        # Formattazione passo per confronto (differenza in secondi)
        def get_sec_km(act):
            return (act.durata / (act.distanza/1000)) if act.distanza > 0 else 0
            
        diff_passo_sec = get_sec_km(act1) - get_sec_km(act2)
        sign = "+" if diff_passo_sec > 0 else "-"
        m, s = divmod(abs(int(diff_passo_sec)), 60)
        delta['passo'] = f"{sign}{m}:{s:02d}"

        context.update({
            'act1': act1,
            'act2': act2,
            'delta': delta,
            'show_comparison': True
        })

    return render(request, 'atleti/confronto.html', context)

def attrezzatura_scarpe(request):
    """Pagina statistiche scarpe e attrezzatura"""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.has_perm('atleti.access_attrezzatura')):
        messages.error(request, "Non hai i permessi per visualizzare l'Attrezzatura.")
        return redirect('home')
        
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Attrezzatura")
    
    # FIX MANUALE: Rinormalizzazione DB su richiesta (per applicare le nuove regex ai dati vecchi)
    if request.GET.get('fix_names'):
        count = 0
        for s in Scarpa.objects.all():
            _, new_model = normalizza_scarpa(s.nome)
            new_model = new_model.strip() # Rimuove spazi extra residui
            if s.modello_normalizzato != new_model:
                print(f"FIX SCARPA: {s.nome} -> {new_model}", flush=True) # DEBUG LOG
                s.modello_normalizzato = new_model
                s.save()
                count += 1
        messages.success(request, f"Database scarpe aggiornato: {count} modelli rinormalizzati.")
        return redirect('attrezzatura_scarpe')

    # Messaggio per Admin per facilitare il fix
    if request.user.is_staff:
        fix_url = request.path + "?fix_names=1"
        messages.info(request, mark_safe(f'🔧 <b>Admin Zone:</b> I nomi delle scarpe sembrano duplicati? <a href="{fix_url}" class="alert-link">Clicca qui per normalizzare il Database</a> (es. Ride 17 -> Ride).'))

    from django.db.models import Count, Avg
    
    # Filtriamo scarpe con almeno 50km per evitare rumore statistico
    qs_scarpe = Scarpa.objects.filter(distanza__gt=50000)
    
    # Loghi Brands (URL statici per evitare scraping complesso)
    logos = BRAND_LOGOS
    
    # Statistiche Brand (Top 10)
    brands_stats_qs = qs_scarpe.values('brand').annotate(
        count=Count('id'),
        avg_dist=Avg('distanza')
    ).order_by('-count')[:10]
    
    brands_stats = []
    for b in brands_stats_qs:
        brands_stats.append({
            'brand': b['brand'],
            'count': b['count'],
            'avg_km': int(b['avg_dist'] / 1000) if b['avg_dist'] else 0,
            'logo': logos.get(b['brand'])
        })
    
    # Statistiche Modelli (Top 20)
    models_stats_qs = qs_scarpe.values('brand', 'modello_normalizzato').annotate(
        count=Count('id'),
        avg_dist=Avg('distanza'),
        max_dist=Max('distanza')
    ).order_by('-count')[:20]
    
    models_stats = []
    for m in models_stats_qs:
        models_stats.append({
            'brand': m['brand'],
            'modello_normalizzato': m['modello_normalizzato'],
            'count': m['count'],
            'max_km': int(m['max_dist'] / 1000) if m['max_dist'] else 0
        })
    
    # Scarpe dell'utente corrente
    user_shoes_qs = Scarpa.objects.filter(atleta__user=request.user, retired=False).order_by('-primary', '-distanza')
    user_shoes = []
    for s in user_shoes_qs:
        s.logo_url = logos.get(s.brand)
        user_shoes.append(s)
        
    # Scarpe dismesse
    retired_shoes_qs = Scarpa.objects.filter(atleta__user=request.user, retired=True).order_by('-distanza')
    retired_shoes = []
    for s in retired_shoes_qs:
        s.logo_url = logos.get(s.brand)
        retired_shoes.append(s)
    
    return render(request, 'atleti/attrezzatura.html', {
        'brands_stats': brands_stats,
        'models_stats': models_stats,
        'user_shoes': user_shoes,
        'retired_shoes': retired_shoes
    })
