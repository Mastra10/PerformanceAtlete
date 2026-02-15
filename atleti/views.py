import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.contrib.auth.decorators import login_required
from allauth.socialaccount.models import SocialToken ,SocialAccount
from django.core.cache import cache
from .models import Attivita, ProfiloAtleta, LogSistema, Scarpa
import math
from .utils import analizza_performance_atleta, calcola_metrica_vo2max, stima_vo2max_atleta, stima_potenza_watt, calcola_trend_atleta, formatta_passo, stima_potenziale_gara, analizza_squadra_coach, calcola_vam_selettiva, refresh_strava_token, processa_attivita_strava, fix_strava_duplicates, normalizza_scarpa, BRAND_LOGOS, analizza_gare_atleta, calcola_vo2max_effettivo, calcola_efficienza, normalizza_dispositivo, genera_commenti_podio_ai, get_atleti_con_statistiche_settimanali, analizza_classifica_settimanale
import time
from django.db.models import Sum, Max, Q, OuterRef, Subquery, Avg, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta, timezone as dt_timezone
import json
from django.contrib.auth.models import User
import csv
from django_apscheduler.models import DjangoJobExecution, DjangoJob
from .models import TaskSettings
from .models import Allenamento, Partecipazione, CommentoAllenamento, Notifica, Team, RichiestaAdesioneTeam
from .forms import AllenamentoForm, CommentoForm, TeamForm, InvitoTeamForm, RegistrazioneUtenteForm
from django.core.management import call_command
from django.contrib import messages
from datetime import timedelta
from django.template.loader import render_to_string
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
import os
from django.core.exceptions import MultipleObjectsReturned
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.utils.dateparse import parse_datetime, parse_duration
from django.views.decorators.csrf import csrf_exempt
from zoneinfo import ZoneInfo

def _get_active_team(request):
    """Helper per recuperare il team attivo dalla sessione"""
    team_id = request.session.get('active_team_id')
    if team_id:
        try:
            return Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            return None
    return None

def _get_navbar_context(request):
    """Helper per popolare i dati della navbar (Team selector)"""
    active_team = _get_active_team(request)
    all_teams = Team.objects.all().order_by('nome')
    # Aggiungiamo info se l'utente è membro per gestire il popup lato frontend
    return {'active_team': active_team, 'all_teams': all_teams}

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
        
    # Calcolo Potenza W/kg (Priorità Mastra-Logic)
    potenza_media_wkg = 0
    if potenza_media > 0 and profilo.peso:
        potenza_media_wkg = round(potenza_media / profilo.peso, 2)

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

    # Calcolo VO2max Effettivo (Mastra-Logic) sulle attività recenti
    vo2_eff_values = [calcola_vo2max_effettivo(a, profilo) for a in chart_data]
    # Filtriamo i None
    vo2_eff_values = [v for v in vo2_eff_values if v is not None]
    vo2max_effettivo_avg = round(sum(vo2_eff_values) / len(vo2_eff_values), 1) if vo2_eff_values else None

    # Calcolo Efficienza Media (EF - Metri/Battito)
    eff_values = [calcola_efficienza(a) for a in chart_data]
    eff_values = [v for v in eff_values if v is not None]
    efficienza_media = round(sum(eff_values) / len(eff_values), 2) if eff_values else None

    # Calcolo Livello Efficienza
    livello_efficienza = ""
    if efficienza_media:
        if efficienza_media >= 1.60: livello_efficienza = "Elite 🏆"
        elif efficienza_media >= 1.40: livello_efficienza = "Eccellente 🥇"
        elif efficienza_media >= 1.20: livello_efficienza = "Buono 🥈"
        elif efficienza_media >= 1.00: livello_efficienza = "Sufficiente 🥉"
        else: livello_efficienza = "Base"

    # Warning Peso
    warning_peso = None
    if not profilo.peso or profilo.peso <= 0:
        warning_peso = "Peso non configurato per l'atleta! Fondamentale impostarlo nei settings. Stiamo assumendo un valore di default (70kg) per i calcoli."

    # Warning Token Strava Scaduto
    warning_token = None
    token_obj = SocialToken.objects.filter(account__user=user, account__provider='strava').first()
    strava_connected = token_obj is not None
    if token_obj and token_obj.expires_at and token_obj.expires_at < timezone.now():
        warning_token = "⚠️ Il tuo token Strava è scaduto. Prova a sincronizzare. Se fallisce, scollega e ricollega l'account nelle Impostazioni."

    # Warning Privacy FC (Dati mancanti)
    warning_privacy_fc = None
    if strava_connected:
        # Controlliamo le ultime 5 corse
        last_runs = Attivita.objects.filter(atleta=profilo, tipo_attivita__in=['Run', 'TrailRun']).order_by('-data')[:5]
        if last_runs.exists():
            missing_fc = sum(1 for r in last_runs if not r.fc_media or r.fc_media == 0)
            # Se più della metà non ha FC, mostriamo l'avviso
            if missing_fc >= len(last_runs) / 2:
                warning_privacy_fc = "⚠️ Dati cardiaci non ricevuti. Per calcolare VO2max e Carico, abilita 'Dati relativi alla salute' nelle impostazioni di Strava o rendi visibile la frequenza cardiaca nelle attività."

    # --- CALCOLO ALLARMI FISIOLOGICI & CARICO ---
    allarmi = []
    
    # 1. Allarme ACWR (Acute:Chronic Workload Ratio)
    # Calcoliamo il carico basato sui "Km Sforzo" (1km + 100m D+)
    today_acwr = timezone.now()
    start_acute = today_acwr - timedelta(days=7)
    start_chronic = today_acwr - timedelta(days=28)
    
    qs_chronic = Attivita.objects.filter(atleta=profilo, data__gte=start_chronic, data__lte=today_acwr)
    
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
    
    # Analizziamo solo se c'è un volume minimo (>10 Km Sforzo/settimana di media)
    if avg_chronic > 10:
        ratio = load_acute / avg_chronic if avg_chronic > 0 else 0
        if ratio >= 1.3:
            allarmi.append({'tipo': 'danger', 'titolo': 'Rischio Infortunio (ACWR)', 'msg': f"Carico Acuto ({int(load_acute)}) eccessivo rispetto al Cronico ({int(avg_chronic)}). Ratio: {ratio:.2f}. Rischio infortunio alto, scarica!"})
        elif ratio <= 0.6:
            allarmi.append({'tipo': 'warning', 'titolo': 'Detraining (ACWR)', 'msg': f"Carico Acuto ({int(load_acute)}) troppo basso rispetto al tuo standard ({int(avg_chronic)}). Ratio: {ratio:.2f}. Stai perdendo forma."})

    # 2. Allarme FC (Trend in aumento > 5%)
    # trends['fc_media'] è la variazione % recente vs storico calcolata da calcola_trend_atleta
    if trends.get('fc_media', 0) > 5:
        allarmi.append({'tipo': 'warning', 'titolo': 'Deriva Cardiaca', 'msg': f"La tua FC media è salita del {trends['fc_media']}% recentemente a parità di passo. Possibile accumulo di fatica o stress."})

    # Recupero Notifiche non lette
    notifiche = Notifica.objects.filter(utente=user, letta=False).order_by('-data_creazione')

    # Check per icona messaggi (conversazioni/risposte)
    has_unread_messages = notifiche.filter(tipo='message').exists()

    # Statistiche Feedback & Affidabilità
    attended_count = Partecipazione.objects.filter(atleta=user, esito_feedback='Presente').count()
    skipped_count = Partecipazione.objects.filter(atleta=user, esito_feedback='Assente').count()
    rinunce_count = Partecipazione.objects.filter(atleta=user, stato='Rinuncia').count()
    
    total_valid = attended_count + skipped_count
    affidabilita = 100
    if total_valid > 0:
        affidabilita = int((attended_count / total_valid) * 100)

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
        'potenza_media_wkg': potenza_media_wkg,
        'fc_media_recent': fc_media_recent,
        'passo_media_recent': passo_media_recent,
        'livello_vo2max': livello_vo2max,
        'livello_vo2max_strada': livello_vo2max_strada,
        'vo2max_effettivo_avg': vo2max_effettivo_avg,
        'efficienza_media': efficienza_media,
        'livello_efficienza': livello_efficienza,
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
        'vo2max_effettivo_tooltip': "VO2max Effettivo (Mastra-Logic): Indicatore di Efficienza (RE). Calcolato rapportando il Costo O2 del tuo passo reale all'impegno cardiaco (%FC Riserva). Se il percorso è collinare (>50m D+), usiamo il Passo Regolato (GAP) per neutralizzare la pendenza. Premia chi corre forte con pulsazioni basse.",
        'efficienza_tooltip': "Efficiency Factor (EF): Misura quanti metri percorri per ogni battito cardiaco. Formula: Velocità (m/min) / FC. Più è alto, più il tuo motore è efficiente (es. > 1.5 è ottimo).",
        'warning_peso': warning_peso,
        'warning_token': warning_token,
        'warning_privacy_fc': warning_privacy_fc,
        'strava_connected': strava_connected,
        'allarmi': allarmi,
        'notifiche_utente': notifiche,
        'has_unread_messages': has_unread_messages,
        'rinunce_count': rinunce_count,
        'affidabilita': affidabilita,
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
    
    # Gestione Default Team al login se non settato
    if request.user.is_authenticated and 'active_team_id' not in request.session:
        if hasattr(request.user, 'profiloatleta') and request.user.profiloatleta.team_preferito:
            request.session['active_team_id'] = request.user.profiloatleta.team_preferito.id
            
    try:
        if request.user.is_authenticated:
            LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Dashboard")
            context = _get_dashboard_context(request.user)
            context.update(_get_navbar_context(request))
            if context.get('warning_token'):
                messages.warning(request, context['warning_token'])
            return render(request, 'atleti/home.html', context)
        return render(request, 'atleti/home.html', {'login_form': AuthenticationForm()})
    except MultipleObjectsReturned:
        # Se il fix preventivo non ha funzionato (es. race condition), riproviamo e ricarichiamo
        print("CRITICAL: MultipleObjectsReturned intercettato in home. Tento fix di emergenza.", flush=True)
        fix_strava_duplicates()
        return redirect('home')

def login_cancelled(request):
    """Gestisce l'annullamento del login social reindirizzando alla home"""
    messages.info(request, "Login annullato.")
    return redirect('home')

def login_standard(request):
    """Gestisce il login standard (username/password)"""
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            LogSistema.objects.create(livello='INFO', azione='Login', utente=user, messaggio="Login standard effettuato.")
            return redirect('home')
        else:
            messages.error(request, "Username o password non validi.")
    return redirect('home')

def registrazione(request):
    """Gestisce la registrazione di utenti standard (senza Strava)"""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = RegistrazioneUtenteForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Il segnale create_user_profile in models.py creerà automaticamente il ProfiloAtleta
            
            # Login automatico dopo la registrazione
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            LogSistema.objects.create(livello='INFO', azione='Registrazione', utente=user, messaggio="Nuovo utente registrato (No Strava).")
            messages.success(request, f"Benvenuto {user.first_name}! Registrazione completata.")
            return redirect('home')
    else:
        form = RegistrazioneUtenteForm()

    context = {
        'form': form,
        'funzioni_incluse': [
            '✅ Partecipazione Allenamenti di Gruppo',
            '✅ Creazione Eventi e Ritrovi',
            '✅ Gestione Team e Community',
            '✅ Diario Manuale (senza import automatico)'
        ],
        'funzioni_escluse': [
            '❌ Sincronizzazione Automatica Attività',
            '❌ Statistiche Avanzate & Analisi AI',
            '❌ Calcolo VO2max e Carico Allenante'
        ]
    }
    return render(request, 'atleti/registrazione.html', context)

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
        context.update(_get_navbar_context(request))
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

        # Gestione Avatar Manuale
        if 'avatar' in request.FILES:
            profilo.avatar = request.FILES['avatar']

        try:
            # Campi opzionali (potrebbero non esserci nel form per utenti No-Strava)
            peso_val = request.POST.get('peso')
            peso = float(peso_val) if peso_val else profilo.peso
            
            fc_riposo_val = request.POST.get('fc_riposo')
            fc_riposo = int(fc_riposo_val) if fc_riposo_val else profilo.fc_riposo
            
            fc_max_val = request.POST.get('fc_max')
            fc_max = int(fc_max_val) if fc_max_val else profilo.fc_max
            
            # Nuovi campi impostazioni
            mostra_peso = request.POST.get('mostra_peso') == 'on'
            dashboard_pubblica = request.POST.get('dashboard_pubblica') == 'on'
            indice_itra = int(request.POST.get('indice_itra') or 0)
            indice_utmb = int(request.POST.get('indice_utmb') or 0)
            importa_attivita_private = request.POST.get('importa_attivita_private') == 'on'
            condividi_metriche = request.POST.get('condividi_metriche') == 'on'
            escludi_statistiche_coach = request.POST.get('escludi_statistiche_coach') == 'on'
            team_preferito_id = request.POST.get('team_preferito')
            
            profilo.peso = peso
            profilo.mostra_peso = mostra_peso
            profilo.peso_manuale = request.POST.get('peso_manuale') == 'on'
            profilo.dashboard_pubblica = dashboard_pubblica
            profilo.importa_attivita_private = importa_attivita_private
            profilo.condividi_metriche = condividi_metriche
            profilo.escludi_statistiche_coach = escludi_statistiche_coach
            profilo.fc_riposo = fc_riposo
            profilo.fc_max = fc_max
            profilo.fc_massima_teorica = fc_max
            
            if team_preferito_id:
                profilo.team_preferito_id = team_preferito_id
            else:
                profilo.team_preferito = None

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
            messages.error(request, "Errore formato dati: controlla di aver inserito numeri validi (usa il punto per i decimali).")
    
    # Passiamo i team per la select
    teams = Team.objects.filter(membri=request.user)
    return render(request, 'atleti/impostazioni.html', {'profilo': profilo, 'strava_connected': strava_connected, 'teams': teams})

@login_required
def aggiorna_dati_profilo(request):
    """Forza l'aggiornamento dei dati anagrafici (Peso, Nome) da Strava tramite API"""
    profilo, _ = ProfiloAtleta.objects.get_or_create(user=request.user)
    
    social_acc = SocialAccount.objects.filter(user=request.user, provider='strava').first()
    if not social_acc:
        messages.error(request, "Nessun account Strava collegato.")
        return redirect('impostazioni')

    token_obj = SocialToken.objects.filter(account=social_acc).first()
    if not token_obj:
        messages.error(request, "Token Strava non trovato.")
        return redirect('impostazioni')

    # Refresh Token per essere sicuri
    access_token = refresh_strava_token(token_obj)
    if not access_token:
        messages.error(request, "Token scaduto. Ricollega Strava.")
        return redirect('impostazioni')
    
    # Chiamata API Diretta
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        res = requests.get("https://www.strava.com/api/v3/athlete", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            
            # Aggiornamento Peso
            weight = data.get('weight')
            if weight is not None:
                profilo.peso = weight
                messages.success(request, f"Peso aggiornato da Strava: {weight} kg")
            else:
                messages.warning(request, "Peso non disponibile su Strava. Verifica di aver concesso i permessi 'profile:read_all'.")
            
            # Aggiornamento Immagine
            img = data.get('profile')
            if img:
                profilo.immagine_profilo = img
            
            profilo.save()
            
            # Aggiorniamo anche i dati locali di allauth per il futuro
            social_acc.extra_data = data
            social_acc.save()
        else:
            messages.error(request, f"Errore API Strava: {res.status_code}")
    except Exception as e:
        messages.error(request, f"Errore connessione: {e}")
            
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
    only_shoes = request.GET.get('only_shoes') == 'true'
    force_full = request.GET.get('force_full') == 'true'
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

    if athlete_res.status_code == 200:
        athlete_data = athlete_res.json()
        # DEBUG: Verifichiamo se Strava ci manda le scarpe
        print(f"DEBUG STRAVA: Trovate {len(athlete_data.get('shoes', []))} scarpe nel profilo.", flush=True)

        # Aggiorniamo il peso SOLO se Strava ce lo fornisce (evita sovrascrittura con 70kg)
        strava_weight = athlete_data.get('weight')
        if strava_weight is not None and not profilo.peso_manuale:
            profilo.peso = strava_weight
            print(f"DEBUG STRAVA: Peso aggiornato a {strava_weight}kg", flush=True)
        elif strava_weight is None:
            print("DEBUG STRAVA: Peso non presente nella risposta API (verificare permessi 'profile:read_all')", flush=True)
        
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

    # Se richiesto solo aggiornamento scarpe, ci fermiamo qui (Sync Rapido)
    if only_shoes:
        messages.success(request, "Scarpe e Attrezzatura aggiornate con successo!")
        return redirect('attrezzatura_scarpe')

    # --- CHECK BLOCCANTE: Se mancano Peso o FC Riposo, STOP ---
    if not profilo.peso or not profilo.fc_riposo:
        LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio="Dati profilo (Peso/FC) mancanti.")
        return redirect('impostazioni')

    # --- 4. SCARICAMENTO ATTIVITÀ (FULL SYNC + CHECKPOINT) ---
    # Cerchiamo l'ultima attività salvata per usare il parametro 'after' (Checkpoint)
    last_activity = Attivita.objects.filter(atleta=profilo).order_by('-data').first()
    timestamp_checkpoint = None
    
    # FIX: Usiamo il checkpoint solo se abbiamo completato con successo almeno una sync in passato (e non è richiesto force_full).
    # Se data_ultima_sincronizzazione è None, significa che la prima sync è fallita o è parziale,
    # quindi forziamo un riscaricamento completo (senza 'after') per recuperare lo storico mancante.
    if last_activity and profilo.data_ultima_sincronizzazione and not force_full:
        # Aggiungiamo 1 secondo per non riscaricare l'ultima attività
        timestamp_checkpoint = int(last_activity.data.timestamp()) + 1
    else:
        LogSistema.objects.create(livello='INFO', azione='Sync Manuale', utente=request.user, messaggio="Avvio download completo (storico/recovery).")

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
                access_token = new_token # Aggiorniamo anche la variabile locale per le chiamate successive (es. VAM)
                headers = {'Authorization': f'Bearer {new_token}'}
                response = requests.get(url_activities, headers=headers, params=params)
            
            if response.status_code == 401:
                # Logghiamo il corpo della risposta per capire il motivo (es. Scope mancanti)
                err_msg = f"Token rifiutato dopo refresh. Strava dice: {response.text[:150]}"
                LogSistema.objects.create(livello='WARNING', azione='Sync Manuale', utente=request.user, messaggio=err_msg)
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
    context.update(_get_navbar_context(request))
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
    
    # 1. Recupero Dati e Podio (Logica spostata in utils)
    atleti, active_atleti, podio = get_atleti_con_statistiche_settimanali()
    
    # FILTRO TEAM
    active_team = _get_active_team(request)
    if active_team:
        # Filtriamo solo gli atleti che sono membri del team attivo
        team_members_ids = active_team.membri.values_list('id', flat=True)
        atleti = [a for a in atleti if a.user.id in team_members_ids]
        active_atleti = [a for a in active_atleti if a.user.id in team_members_ids]
        # Ricalcoliamo il podio locale per il team (Top 3 tra i membri attivi del gruppo)
        podio = sorted(active_atleti, key=lambda x: x.punteggio_podio, reverse=True)[:3]

    # 2. Offuscamento dati sensibili
    if not request.user.is_staff:
        for a in atleti:
            if not a.condividi_metriche:
                a.vo2max_stima_statistica = None 
                a.vo2max_strada = None
                a.indice_itra = 0
                a.indice_utmb = 0

    max_km = max([a.km_week for a in active_atleti]) if active_atleti else 1
    max_dplus = max([a.dplus_week for a in active_atleti]) if active_atleti else 1
    
    # 3. Recupero Commenti AI (SOLO DA CACHE, generati dal task background)
    if podio:
        ai_comments = cache.get("podio_ai_comments_latest")

        # Assegnazione metadati per il template (colori e icone)
        for i, p in enumerate(podio):
            p.podio_rank = i + 1
            # Sovrascriviamo la motivazione algoritmica con quella AI se disponibile in cache
            if ai_comments and p.user.username in ai_comments:
                p.motivazione_podio = ai_comments[p.user.username]

    context = {
        'atleti': atleti,
        'active_atleti': active_atleti,
        'max_km': max_km,
        'max_dplus': max_dplus,
        'podio': podio
    }
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/riepilogo_atleti.html', context)

def analisi_classifica_ai(request):
    """
    API per generare il recap avvincente della classifica settimanale.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Non autorizzato'}, status=401)
    
    # Controllo permessi
    if not (request.user.is_staff or request.user.has_perm('atleti.access_riepilogo')):
        return JsonResponse({'error': 'Permessi insufficienti'}, status=403)

    # Recupero dati
    _, active_atleti, _ = get_atleti_con_statistiche_settimanali()
    
    # Filtro Team (coerente con la vista riepilogo)
    active_team = _get_active_team(request)
    team_name = None
    
    if active_team:
        team_members_ids = active_team.membri.values_list('id', flat=True)
        active_atleti = [a for a in active_atleti if a.user.id in team_members_ids]
        team_name = active_team.nome

    # Generazione Analisi
    analisi_testo = analizza_classifica_settimanale(active_atleti, team_name)
    
    return JsonResponse({'analisi': analisi_testo})

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

    context = {
        'gare': gare,
        'stats': stats,
        'chart_labels': json.dumps(chart_labels),
        'chart_pos': json.dumps(chart_pos),
        'chart_types': json.dumps(chart_types),
        'pie_labels': json.dumps(list(pos_buckets.keys())),
        'pie_data': json.dumps(list(pos_buckets.values())),
        'has_races': gare.exists(), # Flag esplicito per mostrare i grafici
    }
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/gare.html', context)

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

def _get_coach_dashboard_context(week_offset, active_team=None):
    """Helper per calcolare i dati della dashboard coach per una specifica settimana"""
    today = timezone.now()
    current_week_start = today - timedelta(days=today.weekday())
    current_week_start = current_week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    target_week_start = current_week_start + timedelta(weeks=week_offset)
    target_week_end = target_week_start + timedelta(weeks=1)
    prev_week_start = target_week_start - timedelta(weeks=1)

    # Base QuerySets (Escludiamo Mastra e chi ha la privacy attiva)
    base_qs = ProfiloAtleta.objects.exclude(user__username='mastra').exclude(escludi_statistiche_coach=True)
    activity_base_qs = Attivita.objects.exclude(atleta__user__username='mastra').exclude(atleta__escludi_statistiche_coach=True)

    # FILTRO TEAM
    if active_team:
        base_qs = base_qs.filter(user__in=active_team.membri.all())
        activity_base_qs = activity_base_qs.filter(atleta__user__in=active_team.membri.all())

    # 1. Distribuzione VO2max (Pie Chart)
    vo2_ranges = {
        'Elite (>65)': base_qs.filter(vo2max_stima_statistica__gte=65).count(),
        'Eccellente (58-65)': base_qs.filter(vo2max_stima_statistica__gte=58, vo2max_stima_statistica__lt=65).count(),
        'Ottimo (52-58)': base_qs.filter(vo2max_stima_statistica__gte=52, vo2max_stima_statistica__lt=58).count(),
        'Buono (45-52)': base_qs.filter(vo2max_stima_statistica__gte=45, vo2max_stima_statistica__lt=52).count(),
        'Base (<45)': base_qs.filter(vo2max_stima_statistica__lt=45).count(),
    }
    print(f"DEBUG COACH - VO2 Ranges: {vo2_ranges}", flush=True)

    # 1c. Distribuzione VO2max Solo Strada
    vo2_strada_ranges = {
        'Elite (>65)': base_qs.filter(vo2max_strada__gte=65).count(),
        'Eccellente (58-65)': base_qs.filter(vo2max_strada__gte=58, vo2max_strada__lt=65).count(),
        'Ottimo (52-58)': base_qs.filter(vo2max_strada__gte=52, vo2max_strada__lt=58).count(),
        'Buono (45-52)': base_qs.filter(vo2max_strada__gte=45, vo2max_strada__lt=52).count(),
        'Base (<45)': base_qs.filter(vo2max_strada__lt=45).count(),
    }
    print(f"DEBUG COACH - VO2 Strada Ranges: {vo2_strada_ranges}", flush=True)
    
    # 1b. Distribuzione Strada vs Trail (Ultimi 90 giorni rispetto alla settimana visualizzata)
    last_90_days = target_week_end - timedelta(days=90)
    trail_count = activity_base_qs.filter(data__gte=last_90_days, data__lte=target_week_end, tipo_attivita='TrailRun').count()
    road_count = activity_base_qs.filter(data__gte=last_90_days, data__lte=target_week_end, tipo_attivita='Run').count()
    print(f"DEBUG COACH - Trail: {trail_count}, Road: {road_count}", flush=True)

    # 2. Atleti Inattivi (> 7 giorni)
    check_date = target_week_end
    seven_days_before_check = check_date - timedelta(days=7)
    
    # Subquery per trovare l'ultima attività rispetto alla data visualizzata
    last_activity_subquery = Attivita.objects.filter(
        atleta=OuterRef('pk'),
        data__lt=check_date
    ).order_by('-data').values('data')[:1]

    atleti_inattivi = base_qs.annotate(
        last_act=Subquery(last_activity_subquery)
    ).filter(Q(last_act__lt=seven_days_before_check) | Q(last_act__isnull=True)).order_by('last_act')

    # 3. Volume Settimanale Squadra (Trend)
    vol_current = activity_base_qs.filter(data__gte=target_week_start, data__lt=target_week_end).aggregate(Sum('distanza'))['distanza__sum'] or 0
    vol_prev = activity_base_qs.filter(data__gte=prev_week_start, data__lt=target_week_start).aggregate(Sum('distanza'))['distanza__sum'] or 0
    
    vol_current_km = round(vol_current / 1000, 1)
    vol_prev_km = round(vol_prev / 1000, 1)
    
    trend_vol = 0
    if vol_prev_km > 0:
        trend_vol = round(((vol_current_km - vol_prev_km) / vol_prev_km) * 100, 1)

    # 5. Top Ranking (ITRA & UTMB)
    top_itra = base_qs.filter(indice_itra__gt=0).select_related('user').order_by('-indice_itra')[:5]
    top_utmb = base_qs.filter(indice_utmb__gt=0).select_related('user').order_by('-indice_utmb')[:5]
    
    # Definiamo all_atleti qui, prima di usarlo nei cicli successivi
    all_atleti = base_qs.select_related('user').all()

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
    active_team = _get_active_team(request)
    context = _get_coach_dashboard_context(week_offset, active_team)
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/dashboard_coach.html', context)

def analisi_coach_gemini(request):
    """API per generare l'analisi AI della dashboard corrente"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Non autorizzato'}, status=403)
    
    try:
        week_offset = int(request.GET.get('week', 0))
    except ValueError:
        week_offset = 0
        
    active_team = _get_active_team(request)
    context = _get_coach_dashboard_context(week_offset, active_team)
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
    
    # Lettura Log File (Ultime 100 righe)
    log_content = ""
    log_path = '/code/scheduler.log'
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                log_content = "".join(lines[-100:])
        else:
            log_content = "File di log non trovato."
    except Exception as e:
        log_content = f"Errore lettura log: {e}"

    return render(request, 'atleti/scheduler_logs.html', {
        'logs': logs, 
        'tasks': tasks_list, 
        'now': timezone.now(),
        'log_content': log_content
    })

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

    # 1. Log Console (Rimosso per semplificazione)
    log_content = ""
    
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
    qs_atleti = ProfiloAtleta.objects.select_related('user').all().order_by('user__first_name')
    
    active_team = _get_active_team(request)
    if active_team:
        qs_atleti = qs_atleti.filter(user__in=active_team.membri.all())

    context['atleti'] = qs_atleti

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

    context.update(_get_navbar_context(request))
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
    
    # FILTRO TEAM
    active_team = _get_active_team(request)
    if active_team:
        qs_scarpe = qs_scarpe.filter(atleta__user__in=active_team.membri.all())
    
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
    
    context = {
        'brands_stats': brands_stats,
        'models_stats': models_stats,
        'user_shoes': user_shoes,
        'retired_shoes': retired_shoes
    }
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/attrezzatura.html', context)

def statistiche_dispositivi(request):
    """Pagina statistiche sui dispositivi GPS utilizzati"""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.has_perm('atleti.access_attrezzatura')):
        messages.error(request, "Non hai i permessi per visualizzare i Dispositivi.")
        return redirect('home')
        
    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Statistiche Dispositivi")
    
    from django.db.models import Count
    
    # Recuperiamo tutte le attività che hanno un dispositivo registrato
    # Escludiamo Zwift virtuale se vogliamo solo hardware fisico, ma per ora teniamo tutto
    qs = Attivita.objects.filter(dispositivo__isnull=False).exclude(dispositivo='')
    
    # FILTRO TEAM
    active_team = _get_active_team(request)
    if active_team:
        qs = qs.filter(atleta__user__in=active_team.membri.all())
    
    # 1. Statistiche Raw per Modello
    raw_stats = qs.values('dispositivo').annotate(count=Count('atleta', distinct=True)).order_by('-count')
    
    brand_counts = {}
    model_counts = []
    
    total_devices = 0
    
    for item in raw_stats:
        dev_name = item['dispositivo']
        count = item['count']
        total_devices += count
        
        brand, _ = normalizza_dispositivo(dev_name)
        
        # Aggregazione Brand
        brand_counts[brand] = brand_counts.get(brand, 0) + count
        
        # Lista Modelli
        model_counts.append({'modello': dev_name, 'brand': brand, 'count': count})
        
    # Ordina Brand per popolarità
    sorted_brands = sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)
    
    context = {
        'brands': sorted_brands,
        'models': model_counts[:30], # Top 30 modelli
        'total_activities': total_devices
    }
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/dispositivi.html', context)

@login_required
def statistiche_log(request):
    """
    Pagina di statistiche sui log di sistema (Visite, Azioni Utente).
    Visibile solo agli admin.
    """
    if not request.user.is_staff:
        messages.error(request, "Accesso negato.")
        return redirect('home')

    LogSistema.objects.create(livello='INFO', azione='Page View', utente=request.user, messaggio="Visita Statistiche Log")

    # 1. Filtro base: Escludiamo task tecnici/automatici
    # Escludiamo 'Token Refresh', 'Import Attività' (generato da sync), 'Calcolo VAM'
    logs_qs = LogSistema.objects.exclude(azione__in=['Token Refresh', 'Import Attività', 'Calcolo VAM', 'System', 'Token Refresh'])
    
    # 2. Pagine più visitate (Azione = 'Page View')
    # Estraiamo il nome della pagina dal messaggio "Visita [NomePagina]"
    page_logs = logs_qs.filter(azione='Page View').values('messaggio')
    page_counts = {}
    for log in page_logs:
        page = log['messaggio'].replace('Visita ', '')
        page_counts[page] = page_counts.get(page, 0) + 1
    
    # Sort and top 10
    sorted_pages = sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    page_stats = [{'page': k, 'count': v} for k, v in sorted_pages]

    # 3. Utenti più attivi (Top 10)
    user_stats_qs = logs_qs.exclude(utente__isnull=True).values('utente__username', 'utente__first_name', 'utente__last_name').annotate(count=Count('id')).order_by('-count')[:10]
    
    user_stats = []
    for u in user_stats_qs:
        display_name = f"{u['utente__first_name']} {u['utente__last_name']}" if u['utente__first_name'] else u['utente__username']
        user_stats.append({'user': display_name, 'count': u['count']})

    # 4. Distribuzione Azioni (Che cosa fanno gli utenti?)
    # Escludiamo Page View per vedere le azioni "attive" (Sync, Analisi, ecc)
    action_stats_qs = logs_qs.exclude(azione='Page View').values('azione').annotate(count=Count('id')).order_by('-count')
    
    action_stats = [{'azione': item['azione'], 'count': item['count']} for item in action_stats_qs]

    # 5. Attività nel tempo (Ultimi 14 giorni)
    start_date = timezone.now().date() - timedelta(days=14)
    
    # Totale attività (Log totali)
    daily_stats_qs = logs_qs.filter(data__date__gte=start_date).annotate(day=TruncDate('data')).values('day').annotate(count=Count('id')).order_by('day')
    
    # Accessi univoci (Utenti distinti per giorno)
    daily_unique_qs = logs_qs.exclude(utente__isnull=True).filter(data__date__gte=start_date).annotate(day=TruncDate('data')).values('day').annotate(unique_count=Count('utente', distinct=True)).order_by('day')
    
    # Allineamento date (per coprire giorni vuoti e sincronizzare i due dataset)
    stats_dict = {item['day']: item['count'] for item in daily_stats_qs}
    unique_dict = {item['day']: item['unique_count'] for item in daily_unique_qs}
    
    daily_labels = []
    daily_data = []
    daily_unique_data = []
    
    for i in range(15):
        d = start_date + timedelta(days=i)
        daily_labels.append(d.strftime('%d/%m'))
        daily_data.append(stats_dict.get(d, 0))
        daily_unique_data.append(unique_dict.get(d, 0))

    return render(request, 'atleti/statistiche_log.html', {
        'page_stats': page_stats,
        'user_stats': user_stats,
        'action_stats': action_stats,
        'daily_labels': json.dumps(daily_labels),
        'daily_data': json.dumps(daily_data),
        'daily_unique_data': json.dumps(daily_unique_data),
    })

# --- GESTIONE ALLENAMENTI ---

@login_required
def lista_allenamenti(request):
    """Lista allenamenti futuri visibili all'utente"""
    timezone.activate(ZoneInfo("Europe/Rome")) # Assicura visualizzazione orari corretta
    now = timezone.now()
    
    # FILTRO TEAM
    active_team = _get_active_team(request)
    
    qs = Allenamento.objects.filter(data_orario__gte=now)

    # --- FILTRI RICERCA ---
    search_query = request.GET.get('q')
    lat = request.GET.get('lat')
    lon = request.GET.get('lon')
    radius = request.GET.get('radius')

    # 1. Filtro Testuale (Titolo o Luogo)
    # Se c'è una ricerca geografica attiva (raggio impostato), ignoriamo il testo perché è il nome della località centrale
    if search_query and not (lat and lon and radius):
        qs = qs.filter(Q(titolo__icontains=search_query) | Q(luogo__icontains=search_query))

    if active_team:
        # Se siamo in un gruppo, vediamo gli allenamenti del gruppo + quelli Pubblici del Master (team=None)
        qs = qs.filter(
            Q(team=active_team) | 
            (Q(visibilita='Pubblico') & Q(team__isnull=True))
        )
    else:
        # Se siamo nel Master (Tutti), vediamo:
        # 1. Allenamenti Pubblici (di qualsiasi gruppo)
        # 2. Allenamenti Privati dove siamo invitati
        # 3. Allenamenti creati da noi
        # NOTA: Escludiamo esplicitamente quelli con visibilità 'Gruppo' per tenerli segregati
        qs = qs.filter(
            Q(visibilita='Pubblico') | 
            Q(invitati=request.user) | 
            Q(creatore=request.user)
        ).exclude(visibilita='Gruppo').distinct()

    # 2. Filtro Geografico (Raggio KM) - Applicato in Python (SQLite/Postgres base non hanno geo-funzioni native semplici)
    if lat and lon and radius:
        try:
            user_lat = float(lat)
            user_lon = float(lon)
            user_radius = float(radius)
            
            # Funzione Haversine per distanza
            def haversine(lat1, lon1, lat2, lon2):
                R = 6371  # Raggio Terra in km
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                return R * c

            # Filtriamo la lista (ID degli allenamenti validi)
            valid_ids = []
            for a in qs:
                if a.latitudine and a.longitudine:
                    dist = haversine(user_lat, user_lon, a.latitudine, a.longitudine)
                    if dist <= user_radius:
                        valid_ids.append(a.id)
            
            # Riapplichiamo il filtro al QuerySet
            qs = qs.filter(id__in=valid_ids)
        except ValueError:
            pass # Coordinate non valide, ignoriamo il filtro

    qs = qs.annotate(
        num_confermati=Count('partecipanti', filter=Q(partecipanti__stato='Approvata'), distinct=True)
    ).order_by('data_orario').prefetch_related('partecipanti__atleta__profiloatleta')
    
    # Statistiche Partecipazione Globali
    stats = {
        'allenamenti_totali': Allenamento.objects.count(),
        'feedback_pos': Partecipazione.objects.filter(esito_feedback='Presente').count(),
        'feedback_neg': Partecipazione.objects.filter(esito_feedback='Assente').count(),
    }
    
    context = {'allenamenti': qs, 'stats': stats}
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/allenamenti_list.html', context)

@login_required
def storico_allenamenti(request):
    """Lista allenamenti passati (Storico)"""
    timezone.activate(ZoneInfo("Europe/Rome"))
    now = timezone.now()
    
    active_team = _get_active_team(request)
    
    # Base Query: Allenamenti passati
    qs = Allenamento.objects.filter(data_orario__lt=now)

    if active_team:
        # Logica Gruppo: Allenamenti del gruppo + Pubblici del Master (team=None)
        qs = qs.filter(
            Q(team=active_team) | 
            (Q(visibilita='Pubblico') & Q(team__isnull=True))
        )
    else:
        # Logica Master: Pubblici (anche dei gruppi) + Privati invitati + Creati da me
        qs = qs.filter(
            Q(visibilita='Pubblico') | 
            Q(invitati=request.user) | 
            Q(creatore=request.user)
        ).exclude(visibilita='Gruppo').distinct()

    qs = qs.annotate(
        num_confermati=Count('partecipanti', filter=Q(partecipanti__stato='Approvata'), distinct=True)
    ).order_by('-data_orario').prefetch_related('partecipanti__atleta__profiloatleta')
    
    # Riutilizziamo lo stesso template ma con flag is_history
    context = {'allenamenti': qs, 'is_history': True}
    context.update(_get_navbar_context(request))
    return render(request, 'atleti/allenamenti_list.html', context)

@login_required
def crea_allenamento(request):
    timezone.activate(ZoneInfo("Europe/Rome")) # Attiva fuso orario per GET (form) e POST (salvataggio)
    active_team = _get_active_team(request)
    if request.method == 'POST':
        form = AllenamentoForm(request.POST, request.FILES)
        if form.is_valid():
            allenamento = form.save(commit=False)
            allenamento.creatore = request.user
            
            # FIX TIMEZONE: Intercettiamo il dato grezzo e forziamo Europe/Rome
            # Questo impedisce a Django di usare UTC di default se l'ambiente è configurato male
            raw_data = request.POST.get('data_orario')
            if raw_data:
                try:
                    dt_naive = parse_datetime(raw_data)
                    if dt_naive and timezone.is_naive(dt_naive):
                        allenamento.data_orario = timezone.make_aware(dt_naive, ZoneInfo("Europe/Rome"))
                except Exception:
                    pass # Se fallisce, usiamo quello che ha capito il form
            
            # --- AUTO-FILL DA GPX ---
            if allenamento.file_gpx:
                try:
                    import gpxpy
                    # Assicuriamoci di leggere il file dall'inizio
                    if hasattr(allenamento.file_gpx, 'seek'):
                        allenamento.file_gpx.seek(0)
                    
                    gpx = gpxpy.parse(allenamento.file_gpx)
                    
                    # Calcolo Distanza (m -> km)
                    dist_m = gpx.length_2d()
                    if dist_m > 0:
                        allenamento.distanza_km = round(dist_m / 1000, 2)
                    
                    # Calcolo Dislivello
                    uphill, downhill = gpx.get_uphill_downhill()
                    if uphill > 0:
                        allenamento.dislivello = int(uphill)
                        
                    # Estrazione Coordinate Partenza (Lat/Lon)
                    if gpx.tracks and gpx.tracks[0].segments and gpx.tracks[0].segments[0].points:
                        start_point = gpx.tracks[0].segments[0].points[0]
                        allenamento.latitudine = start_point.latitude
                        allenamento.longitudine = start_point.longitude
                except ImportError:
                    messages.warning(request, "Libreria 'gpxpy' non installata. Impossibile estrarre dati dal GPX.")
                except Exception as e:
                    messages.warning(request, f"Errore lettura GPX: {e}")
            
            # --- FALLBACK GEOCODING SERVER-SIDE ---
            # Se l'utente ha scritto il luogo ma non ha selezionato l'autocomplete (o JS ha fallito)
            if allenamento.luogo and (not allenamento.latitudine or not allenamento.longitudine):
                try:
                    query = allenamento.luogo
                    if allenamento.indirizzo:
                        query = f"{allenamento.indirizzo}, {allenamento.luogo}"
                        
                    headers = {'User-Agent': 'BarillaMonitor/1.0'}
                    url = "https://nominatim.openstreetmap.org/search"
                    params = {'format': 'json', 'q': query, 'limit': 1}
                    res = requests.get(url, headers=headers, params=params, timeout=5)
                    if res.status_code == 200:
                        data = res.json()
                        if data:
                            allenamento.latitudine = float(data[0]['lat'])
                            allenamento.longitudine = float(data[0]['lon'])
                except Exception as e:
                    print(f"Errore Geocoding Server-Side: {e}")
            # ------------------------
            
            # Fallback se i campi sono vuoti e non c'è GPX (o errore GPX)
            if allenamento.distanza_km is None: allenamento.distanza_km = 0.0
            if allenamento.dislivello is None: allenamento.dislivello = 0
            
            # Assegna al team attivo se presente
            if active_team:
                allenamento.team = active_team

            allenamento.save()
            
            # Aggiungi creatore come partecipante confermato (così appare nella lista)
            Partecipazione.objects.create(
                allenamento=allenamento,
                atleta=request.user,
                stato='Approvata'
            )
            
            form.save_m2m() # Salva gli invitati
            
            # --- CREAZIONE NOTIFICHE ---
            messaggio = f"Nuovo allenamento di gruppo: {allenamento.titolo} ({allenamento.data_orario.strftime('%d/%m')}) organizzato da {request.user.first_name}."
            link_url = reverse('dettaglio_allenamento', args=[allenamento.pk])
            
            destinatari = []
            if allenamento.visibilita == 'Pubblico':
                # Tutti tranne il creatore
                destinatari = User.objects.exclude(id=request.user.id)
            elif allenamento.visibilita == 'Gruppo' and active_team:
                # Tutti i membri del gruppo tranne il creatore
                destinatari = active_team.membri.exclude(id=request.user.id)
            else:
                # Solo gli invitati
                destinatari = allenamento.invitati.all()
            
            notifiche_objs = [
                Notifica(utente=u, messaggio=messaggio, link=link_url, tipo='info')
                for u in destinatari
            ]
            Notifica.objects.bulk_create(notifiche_objs)
            # ---------------------------

            messages.success(request, "Allenamento creato con successo!")
            return redirect('lista_allenamenti')
    else:
        form = AllenamentoForm()
    return render(request, 'atleti/allenamento_form.html', {'form': form})

def dettaglio_allenamento(request, pk):
    allenamento = get_object_or_404(Allenamento, pk=pk)
    timezone.activate(ZoneInfo("Europe/Rome")) # Assicura visualizzazione orari corretta
    
    # Gestione Commenti
    if request.user.is_authenticated and request.method == 'POST' and 'commento' in request.POST:
        c_form = CommentoForm(request.POST)
        if c_form.is_valid():
            comm = c_form.save(commit=False)
            comm.allenamento = allenamento
            comm.autore = request.user
            comm.save()
            
            # --- NOTIFICHE COMMENTI (SCAMBIO INFORMAZIONI) ---
            # Identifica interessati: Creatore + chi ha già commentato (escluso chi scrive ora)
            recipient_ids = set()
            if allenamento.creatore != request.user:
                recipient_ids.add(allenamento.creatore.id)
            
            # Aggiungi altri partecipanti alla discussione
            prev_authors = allenamento.commenti.exclude(autore=request.user).values_list('autore_id', flat=True)
            recipient_ids.update(prev_authors)
            
            if recipient_ids:
                recipients = User.objects.filter(id__in=recipient_ids)
                msg = f"Nuova risposta in: {allenamento.titolo}"
                link = reverse('dettaglio_allenamento', args=[pk])
                
                notifiche_objs = [Notifica(utente=u, messaggio=msg, link=link, tipo='message') for u in recipients]
                Notifica.objects.bulk_create(notifiche_objs)
            # -------------------------------------------------

            return redirect('dettaglio_allenamento', pk=pk)
    
    # Gestione Adesione
    if request.user.is_authenticated and request.method == 'POST' and 'join' in request.POST:
        part, created = Partecipazione.objects.get_or_create(allenamento=allenamento, atleta=request.user)
        if created:
            part.check_risk() # Calcola rischio
            part.save()
            
            # --- NOTIFICA ORGANIZZATORE ---
            if allenamento.creatore != request.user:
                Notifica.objects.create(
                    utente=allenamento.creatore,
                    messaggio=f"{request.user.first_name} vuole partecipare a: {allenamento.titolo}",
                    link=reverse('dettaglio_allenamento', args=[pk]),
                    tipo='info'
                )
            
            messages.success(request, "Richiesta inviata!")
        return redirect('dettaglio_allenamento', pk=pk)
        
    # Gestione Rinuncia (Togliersi dall'allenamento)
    if request.user.is_authenticated and request.method == 'POST' and 'rinuncia' in request.POST:
        part = Partecipazione.objects.filter(allenamento=allenamento, atleta=request.user).first()
        if part and part.stato in ['Richiesta', 'Approvata']:
            motivo = request.POST.get('motivo_rinuncia')
            part.stato = 'Rinuncia'
            part.motivo_rinuncia = motivo if motivo else "Rinuncia volontaria"
            part.save()
            
            if allenamento.creatore != request.user:
                Notifica.objects.create(
                    utente=allenamento.creatore,
                    messaggio=f"{request.user.first_name} ha rinunciato a: {allenamento.titolo}",
                    link=reverse('dettaglio_allenamento', args=[pk]),
                    tipo='warning'
                )
            messages.warning(request, "Hai rinunciato all'allenamento.")
        return redirect('dettaglio_allenamento', pk=pk)

    partecipazione_utente = None
    if request.user.is_authenticated:
        partecipazione_utente = Partecipazione.objects.filter(allenamento=allenamento, atleta=request.user).first()
        
    partecipanti = Partecipazione.objects.filter(allenamento=allenamento).select_related('atleta', 'atleta__profiloatleta')
    num_confermati = partecipanti.filter(stato='Approvata').count()
    commenti = allenamento.commenti.all().order_by('data')
    
    return render(request, 'atleti/allenamento_detail.html', {
        'allenamento': allenamento,
        'partecipazione_utente': partecipazione_utente,
        'partecipanti': partecipanti,
        'num_confermati': num_confermati,
        'commenti': commenti,
        'commento_form': CommentoForm() if request.user.is_authenticated else None
    })

@login_required
def gestisci_partecipazione(request, pk, action):
    """Approva o Rifiuta una partecipazione (Solo Creatore)"""
    partecipazione = get_object_or_404(Partecipazione, pk=pk)
    
    if request.user != partecipazione.allenamento.creatore:
        messages.error(request, "Non sei autorizzato.")
        return redirect('dettaglio_allenamento', pk=partecipazione.allenamento.pk)
        
    if action == 'approve':
        partecipazione.stato = 'Approvata'
        partecipazione.save()
    elif action == 'reject':
        motivo = request.POST.get('motivo', 'Non specificato')
        partecipazione.stato = 'Rifiutata'
        partecipazione.motivo_rifiuto = motivo
        partecipazione.save()
        
    return redirect('dettaglio_allenamento', pk=partecipazione.allenamento.pk)

@login_required
def modifica_allenamento(request, pk):
    allenamento = get_object_or_404(Allenamento, pk=pk)
    if request.user != allenamento.creatore:
        messages.error(request, "Non sei autorizzato a modificare questo allenamento.")
        return redirect('dettaglio_allenamento', pk=pk)
    
    timezone.activate(ZoneInfo("Europe/Rome")) # Attiva fuso orario per GET e POST
    
    if request.method == 'POST':
        form = AllenamentoForm(request.POST, request.FILES, instance=allenamento)
        if form.is_valid():
            obj = form.save(commit=False)
            
            # FIX TIMEZONE ANCHE IN MODIFICA
            raw_data = request.POST.get('data_orario')
            if raw_data:
                try:
                    dt_naive = parse_datetime(raw_data)
                    if dt_naive and timezone.is_naive(dt_naive):
                        obj.data_orario = timezone.make_aware(dt_naive, ZoneInfo("Europe/Rome"))
                except Exception:
                    pass
            
            # Se c'è un nuovo file GPX, ricalcoliamo i dati
            if 'file_gpx' in request.FILES:
                try:
                    import gpxpy
                    if hasattr(obj.file_gpx, 'seek'): obj.file_gpx.seek(0)
                    gpx = gpxpy.parse(obj.file_gpx)
                    if gpx.length_2d() > 0: obj.distanza_km = round(gpx.length_2d() / 1000, 2)
                    uphill, _ = gpx.get_uphill_downhill()
                    if uphill > 0: obj.dislivello = int(uphill)
                    
                    # Aggiorna coordinate se GPX cambia
                    if gpx.tracks and gpx.tracks[0].segments and gpx.tracks[0].segments[0].points:
                        pt = gpx.tracks[0].segments[0].points[0]
                        obj.latitudine = pt.latitude
                        obj.longitudine = pt.longitude
                except Exception:
                    pass # Ignoriamo errori GPX in modifica
            
            # --- FALLBACK GEOCODING SERVER-SIDE (Anche in modifica) ---
            if obj.luogo and (not obj.latitudine or not obj.longitudine):
                try:
                    query = obj.luogo
                    if obj.indirizzo:
                        query = f"{obj.indirizzo}, {obj.luogo}"
                        
                    headers = {'User-Agent': 'BarillaMonitor/1.0'}
                    url = "https://nominatim.openstreetmap.org/search"
                    params = {'format': 'json', 'q': query, 'limit': 1}
                    res = requests.get(url, headers=headers, params=params, timeout=5)
                    if res.status_code == 200 and res.json():
                        data = res.json()[0]
                        obj.latitudine = float(data['lat'])
                        obj.longitudine = float(data['lon'])
                except Exception:
                    pass

            obj.save()
            form.save_m2m()
            messages.success(request, "Allenamento aggiornato!")
            return redirect('dettaglio_allenamento', pk=pk)
    else:
        form = AllenamentoForm(instance=allenamento)
    return render(request, 'atleti/allenamento_form.html', {'form': form, 'is_edit': True})

@login_required
def elimina_allenamento(request, pk):
    allenamento = get_object_or_404(Allenamento, pk=pk)
    if request.user == allenamento.creatore:
        allenamento.delete()
        messages.success(request, "Allenamento eliminato.")
    return redirect('lista_allenamenti')

@login_required
def segna_notifica_letta(request, pk):
    if request.method == 'POST':
        notifica = get_object_or_404(Notifica, pk=pk, utente=request.user)
        notifica.letta = True
        notifica.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid method'}, status=400)

def download_allenamento_ics(request, pk):
    """Genera un file .ics per aggiungere l'allenamento al calendario"""
    allenamento = get_object_or_404(Allenamento, pk=pk)
    
    dt_start = allenamento.data_orario
    dt_end = dt_start + allenamento.tempo_stimato
    
    def format_ics_dt(dt):
        return dt.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Mastra Monitor//Allenamenti//IT
BEGIN:VEVENT
UID:allenamento-{allenamento.id}@mastramonitor
DTSTAMP:{format_ics_dt(timezone.now())}
DTSTART:{format_ics_dt(dt_start)}
DTEND:{format_ics_dt(dt_end)}
SUMMARY:🏃 {allenamento.titolo}
DESCRIPTION:{allenamento.descrizione or 'Allenamento di gruppo'} \\n\\nDistanza: {allenamento.distanza_km}km\\nDislivello: {allenamento.dislivello}m D+
END:VEVENT
END:VCALENDAR"""

    response = HttpResponse(ics_content, content_type='text/calendar')
    response['Content-Disposition'] = f'attachment; filename="allenamento_{allenamento.id}.ics"'
    return response

def download_allenamento_gpx(request, pk):
    """Scarica il file GPX dell'allenamento se presente"""
    allenamento = get_object_or_404(Allenamento, pk=pk)
    
    if not allenamento.file_gpx:
        messages.error(request, "Nessun file GPX caricato per questo allenamento.")
        return redirect('dettaglio_allenamento', pk=pk)
        
    try:
        response = HttpResponse(allenamento.file_gpx.open('rb'), content_type='application/gpx+xml')
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(allenamento.file_gpx.name)}"'
        return response
    except FileNotFoundError:
        messages.error(request, "File GPX non trovato sul server.")
        return redirect('dettaglio_allenamento', pk=pk)

# --- GESTIONE TEAM ---

@login_required
def crea_team(request):
    if request.method == 'POST':
        form = TeamForm(request.POST, request.FILES)
        if form.is_valid():
            team = form.save(commit=False)
            team.creatore = request.user
            team.save()
            team.membri.add(request.user) # Il creatore è membro automatico
            messages.success(request, f"Gruppo '{team.nome}' creato con successo!")
            return redirect('home')
    else:
        form = TeamForm()
    return render(request, 'atleti/team_form.html', {'form': form})

@login_required
def gestisci_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    if request.user != team.creatore:
        messages.error(request, "Non sei il creatore di questo gruppo.")
        return redirect('home')

    if request.method == 'POST':
        form = InvitoTeamForm(request.POST)
        if form.is_valid():
            utente_invitato = form.cleaned_data['utente']
            if utente_invitato in team.membri.all():
                messages.warning(request, f"{utente_invitato.first_name} è già nel gruppo.")
            elif RichiestaAdesioneTeam.objects.filter(team=team, utente=utente_invitato, tipo='Invito', stato='In Attesa').exists():
                messages.warning(request, "Invito già inviato.")
            else:
                # Crea invito
                RichiestaAdesioneTeam.objects.create(
                    team=team, 
                    utente=utente_invitato, 
                    tipo='Invito', 
                    stato='In Attesa'
                )
                # Notifica all'utente
                Notifica.objects.create(
                    utente=utente_invitato,
                    messaggio=f"{request.user.first_name} ti ha invitato nel gruppo '{team.nome}'",
                    link=reverse('home'), # L'utente vedrà la notifica e potrà accettare dalla home o lista notifiche
                    tipo='info'
                )
                messages.success(request, f"Invito inviato a {utente_invitato.first_name}.")
    else:
        form = InvitoTeamForm()

    # Lista membri e richieste in sospeso
    membri = team.membri.all()
    richieste_adesione = RichiestaAdesioneTeam.objects.filter(team=team, tipo='Adesione', stato='In Attesa')
    inviti_pendenti = RichiestaAdesioneTeam.objects.filter(team=team, tipo='Invito', stato='In Attesa')

    return render(request, 'atleti/gestione_team.html', {
        'team': team, 
        'form': form, 
        'membri': membri,
        'richieste_adesione': richieste_adesione,
        'inviti_pendenti': inviti_pendenti
    })

@login_required
def elimina_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    if request.user != team.creatore:
        messages.error(request, "Non autorizzato.")
        return redirect('home')
    
    nome_team = team.nome
    team.delete()
    
    if request.session.get('active_team_id') == team_id:
        del request.session['active_team_id']
        
    messages.success(request, f"Gruppo '{nome_team}' eliminato.")
    return redirect('home')

@login_required
def switch_team(request, team_id):
    """Cambia il contesto del gruppo attivo"""
    if team_id == 0:
        # Gruppo Master (Tutti)
        if 'active_team_id' in request.session:
            del request.session['active_team_id']
        messages.info(request, "Visualizzazione: Gruppo Master (Tutti)")
    else:
        team = get_object_or_404(Team, pk=team_id)
        # Controllo se l'utente è membro
        if request.user in team.membri.all():
            request.session['active_team_id'] = team.id
            messages.success(request, f"Visualizzazione: {team.nome}")
        else:
            messages.error(request, "Non sei membro di questo gruppo. Richiedi l'accesso.")
    
    return redirect(request.META.get('HTTP_REFERER', 'home'))

@login_required
def richiedi_adesione_team(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    
    # Verifica se esiste già richiesta
    if RichiestaAdesioneTeam.objects.filter(team=team, utente=request.user).exists():
        messages.warning(request, "Hai già inviato una richiesta per questo gruppo.")
    else:
        RichiestaAdesioneTeam.objects.create(team=team, utente=request.user, tipo='Adesione')
        
        # Notifica al creatore
        Notifica.objects.create(
            utente=team.creatore,
            messaggio=f"{request.user.first_name} chiede di entrare nel gruppo '{team.nome}'",
            link=reverse('home'), # Idealmente una pagina gestione richieste, per ora home
            tipo='info'
        )
        messages.success(request, "Richiesta inviata al creatore del gruppo.")
        
    return redirect(request.META.get('HTTP_REFERER', 'home'))

@login_required
def gestisci_adesione_team(request, richiesta_id, azione):
    """Il CREATORE accetta/rifiuta la richiesta di un utente"""
    richiesta = get_object_or_404(RichiestaAdesioneTeam, pk=richiesta_id)
    
    if request.user != richiesta.team.creatore:
        messages.error(request, "Non autorizzato.")
        return redirect('home')
        
    if azione == 'accetta':
        richiesta.stato = 'Approvata'
        richiesta.save()
        richiesta.team.membri.add(richiesta.utente)
        Notifica.objects.create(utente=richiesta.utente, messaggio=f"Benvenuto! Sei stato aggiunto al gruppo '{richiesta.team.nome}'", tipo='success')
        messages.success(request, f"{richiesta.utente.first_name} aggiunto al gruppo.")
    elif azione == 'rifiuta':
        richiesta.stato = 'Rifiutata'
        richiesta.save()
        messages.info(request, "Richiesta rifiutata.")
        
    return redirect('home')

@login_required
def gestisci_invito_utente(request, richiesta_id, azione):
    """L'UTENTE accetta/rifiuta l'invito del creatore"""
    richiesta = get_object_or_404(RichiestaAdesioneTeam, pk=richiesta_id)
    
    if request.user != richiesta.utente:
        messages.error(request, "Non autorizzato.")
        return redirect('home')
        
    if azione == 'accetta':
        richiesta.stato = 'Approvata'
        richiesta.save()
        richiesta.team.membri.add(request.user)
        messages.success(request, f"Benvenuto nel gruppo '{richiesta.team.nome}'!")
        # Switch automatico al nuovo gruppo
        request.session['active_team_id'] = richiesta.team.id
    elif azione == 'rifiuta':
        richiesta.stato = 'Rifiutata'
        richiesta.save()
        messages.info(request, "Invito rifiutato.")
        
    return redirect('home')

@login_required
def serve_team_image(request, team_id):
    """Serve l'immagine del team tramite Django per evitare problemi di permessi Nginx"""
    team = get_object_or_404(Team, pk=team_id)
    if not team.immagine:
        raise Http404("Nessuna immagine")
    
    try:
        return FileResponse(team.immagine.open('rb'))
    except FileNotFoundError:
        raise Http404("File non trovato")

# --- API PER APP MOBILE ---

@csrf_exempt
def api_login(request):
    """API per effettuare il login dall'App Mobile"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
            
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                # In un'app reale useresti un Token (es. DRF Token), 
                # ma per iniziare questo crea la sessione anche per le chiamate successive
                return JsonResponse({
                    'success': True, 
                    'username': user.username,
                    'sessionid': request.session.session_key
                })
            else:
                return JsonResponse({'error': 'Credenziali non valide'}, status=401)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Metodo non consentito'}, status=405)

def api_get_dashboard(request):
    """API per restituire i dati della dashboard in formato JSON"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Autenticazione richiesta'}, status=401)
    
    try:
        context = _get_dashboard_context(request.user)
        profilo = context['profilo']
        
        # Serializzazione Profilo
        profilo_data = {
            'nome': request.user.first_name,
            'cognome': request.user.last_name,
            'peso': profilo.peso,
            'fc_max': profilo.fc_massima_teorica,
            'fc_riposo': profilo.fc_riposo,
            'vo2max_statistico': profilo.vo2max_stima_statistica,
            'vo2max_strada': profilo.vo2max_strada,
            'itra_index': profilo.indice_itra,
            'utmb_index': profilo.indice_utmb,
            'immagine': profilo.immagine_profilo,
        }
        
        # Serializzazione Attività Recenti
        attivita_data = []
        for act in context['attivita_recenti']:
            attivita_data.append({
                'id': act.id,
                'nome': act.nome,
                'data': act.data.isoformat(),
                'distanza_km': act.distanza_km,
                'dislivello': act.dislivello,
                'tempo': act.durata_formattata,
                'tipo': act.tipo_attivita,
                'vo2max': act.vo2max_stimato,
                'fc_media': act.fc_media,
                'passo': act.passo_medio,
                'vam': act.vam,
                'potenza': act.potenza_media
            })
            
        # Serializzazione Allarmi
        allarmi_data = context['allarmi']
        
        # Serializzazione Notifiche
        notifiche_data = []
        for n in context['notifiche_utente']:
            notifiche_data.append({
                'id': n.id,
                'messaggio': n.messaggio,
                'link': n.link,
                'letta': n.letta,
                'data': n.data_creazione.isoformat(),
                'tipo': n.tipo
            })

        # Aggiungiamo inviti pendenti ai team nella risposta API o Dashboard
        inviti_team = RichiestaAdesioneTeam.objects.filter(utente=request.user, tipo='Invito', stato='In Attesa')
        for inv in inviti_team:
            # Li mostriamo come notifiche speciali
            notifiche_data.insert(0, {
                'id': f"inv_{inv.id}",
                'messaggio': f"Invito Gruppo: {inv.team.nome}. Accetti?",
                'link': f"/team/invito/{inv.id}/accetta/", # Semplificazione per API
                'letta': False,
                'data': inv.data_richiesta.isoformat(),
                'tipo': 'action_required'
            })

        response_data = {
            'stats': {
                'totale_km': context['totale_km'],
                'dislivello_totale': context['dislivello_totale'],
                'dislivello_settimanale': context['dislivello_settimanale'],
                'annuale_km': context['annuale_km'],
                'dislivello_annuale': context['dislivello_annuale'],
                'avg_weekly_km': context['avg_weekly_km'],
                'avg_weekly_elev': context['avg_weekly_elev'],
                'vam_media': context['vam_media'],
                'potenza_media': context['potenza_media'],
                'fc_media_recent': context['fc_media_recent'],
                'passo_media_recent': context['passo_media_recent'],
            },
            'levels': {
                'vo2max': context['livello_vo2max'],
                'vo2max_strada': context['livello_vo2max_strada'],
                'vam': context['livello_vam'],
                'potenza': context['livello_potenza'],
                'itra': context['livello_itra'],
                'utmb': context['livello_utmb'],
                'efficienza': context['livello_efficienza']
            },
            'thresholds': {
                'aerobica': context['soglia_aerobica'],
                'anaerobica': context['soglia_anaerobica']
            },
            'trends': context['trends'],
            'profilo': profilo_data,
            'attivita_recenti': attivita_data,
            'allarmi': allarmi_data,
            'notifiche': notifiche_data,
        }
        
        return JsonResponse(response_data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_list_workouts(request):
    """API per listare gli allenamenti futuri"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Autenticazione richiesta'}, status=401)
        
    now = timezone.now()
    qs = Allenamento.objects.filter(
        Q(visibilita='Pubblico') | 
        Q(invitati=request.user) | 
        Q(creatore=request.user)
    ).filter(data_orario__gte=now).distinct().order_by('data_orario')
    
    data = []
    for a in qs:
        partecipanti_count = a.partecipanti.filter(stato='Approvata').count()
        is_participant = a.partecipanti.filter(atleta=request.user).exists()
        
        data.append({
            'id': a.id,
            'titolo': a.titolo,
            'descrizione': a.descrizione,
            'data': a.data_orario.isoformat(),
            'distanza_km': a.distanza_km,
            'dislivello': a.dislivello,
            'tipo': a.tipo,
            'creatore': f"{a.creatore.first_name} {a.creatore.last_name}",
            'partecipanti_count': partecipanti_count,
            'is_participant': is_participant,
            'visibilita': a.visibilita
        })
        
    return JsonResponse({'allenamenti': data})

@csrf_exempt
def api_create_workout(request):
    """API per creare un nuovo allenamento"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Autenticazione richiesta'}, status=401)
        
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo non consentito'}, status=405)
        
    try:
        data = json.loads(request.body)
        
        # Validazione campi obbligatori
        required_fields = ['titolo', 'data_orario', 'distanza_km', 'dislivello', 'tempo_stimato']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Campo mancante: {field}'}, status=400)
        
        # Parsing Data
        dt = parse_datetime(data['data_orario'])
        if not dt:
            return JsonResponse({'error': 'Formato data non valido (usa ISO 8601)'}, status=400)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, ZoneInfo("Europe/Rome"))
            
        # Parsing Durata
        duration = parse_duration(data['tempo_stimato']) # Es. "01:30:00"
        if not duration:
             return JsonResponse({'error': 'Formato durata non valido (HH:MM:SS)'}, status=400)

        allenamento = Allenamento.objects.create(
            creatore=request.user,
            titolo=data['titolo'],
            descrizione=data.get('descrizione', ''),
            data_orario=dt,
            distanza_km=float(data['distanza_km']),
            dislivello=int(data['dislivello']),
            tipo=data.get('tipo', 'Strada'),
            tempo_stimato=duration,
            visibilita=data.get('visibilita', 'Pubblico')
        )
        
        # Aggiungi creatore come partecipante
        Partecipazione.objects.create(
            allenamento=allenamento,
            atleta=request.user,
            stato='Approvata'
        )
        
        # Creazione Notifiche
        messaggio = f"Nuovo allenamento di gruppo: {allenamento.titolo} ({allenamento.data_orario.strftime('%d/%m')}) organizzato da {request.user.first_name}."
        link_url = reverse('dettaglio_allenamento', args=[allenamento.pk])
        
        destinatari = []
        if allenamento.visibilita == 'Pubblico':
            destinatari = User.objects.exclude(id=request.user.id)
        
        notifiche_objs = [
            Notifica(utente=u, messaggio=messaggio, link=link_url, tipo='info')
            for u in destinatari
        ]
        Notifica.objects.bulk_create(notifiche_objs)
        
        return JsonResponse({'success': True, 'id': allenamento.id, 'message': 'Allenamento creato con successo'})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON non valido'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
