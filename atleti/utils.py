from google import genai
import json
import re
import requests
import os
from .models import Attivita, ProfiloAtleta, LogSistema
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Max, Q, Avg
from allauth.socialaccount.models import SocialApp


def formatta_passo(velocita_ms):
    """Converte velocità m/s in passo min/km (es. 5:30)"""
    if velocita_ms > 0:
        secondi_al_km = 1000 / (velocita_ms * 60)
        minuti = int(secondi_al_km)
        secondi = int((secondi_al_km - minuti) * 60)
        return f"{minuti}:{secondi:02d}"
    return "0:00"

def refresh_strava_token(token_obj, buffer_minutes=10, force=False):
    """
    Controlla se il token è scaduto e lo rinnova usando il refresh_token.
    Restituisce il token valido (stringa) o None se fallisce.
    buffer_minutes: Minuti di anticipo con cui rinnovare il token (default 10).
    force: Se True, tenta il rinnovo ignorando la data di scadenza salvata (utile per errori 401).
    """
    # Se NON è forzato e il token scade tra meno di buffer_minutes (o è già scaduto), lo rinnoviamo
    if not force and token_obj.expires_at and token_obj.expires_at > timezone.now() + timedelta(minutes=buffer_minutes):
        return token_obj.token

    if not token_obj.token_secret:
        LogSistema.objects.create(livello='ERROR', azione='Token Refresh', utente=token_obj.account.user, messaggio="Refresh Token mancante. Necessario nuovo login.")
        return None

    msg = "Token scaduto. Tento rinnovo..." if not force else "Refresh Forzato (Recovery 401)..."
    LogSistema.objects.create(livello='INFO', azione='Token Refresh', utente=token_obj.account.user, messaggio=msg)
    
    try:
        # Recuperiamo le credenziali dell'app
        app = token_obj.app
        
        # FIX: Se il token è orfano (app=None), cerchiamo l'app Strava nel DB e riassociamo
        if not app:
            app = SocialApp.objects.filter(provider='strava').first()
            if app:
                token_obj.app = app
                token_obj.save()
        
        if not app:
            LogSistema.objects.create(livello='ERROR', azione='Token Refresh', utente=token_obj.account.user, messaggio="App Strava non trovata. Impossibile rinnovare il token.")
            return None
        
        data = {
            'client_id': app.client_id,
            'client_secret': app.secret,
            'grant_type': 'refresh_token',
            'refresh_token': token_obj.token_secret, 
        }
        
        response = requests.post('https://www.strava.com/oauth/token', data=data, timeout=10)
        
        if response.status_code == 200:
            new_data = response.json()
            token_obj.token = new_data['access_token']
            token_obj.token_secret = new_data['refresh_token']
            token_obj.expires_at = timezone.now() + timedelta(seconds=new_data['expires_in'])
            token_obj.save()
            
            # Logghiamo eventuali info sugli scope per debug
            scopes = new_data.get('scope', 'N/A')
            LogSistema.objects.create(livello='INFO', azione='Token Refresh', utente=token_obj.account.user, messaggio=f"Token Strava rinnovato. Scopes: {scopes}")
            return token_obj.token
        else:
            LogSistema.objects.create(livello='ERROR', azione='Token Refresh', utente=token_obj.account.user, messaggio=f"ERRORE Refresh: {response.text}")
            return None
    except Exception as e:
        LogSistema.objects.create(livello='ERROR', azione='Token Refresh', utente=token_obj.account.user, messaggio=f"Eccezione: {e}")
        return None

def calcola_vam_selettiva(activity_id, access_token):
    """
    Scarica gli stream dell'attività da Strava e calcola la VAM
    solo sui tratti con pendenza > 7%.
    """
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    params = {
        'keys': 'grade_smooth,altitude,time',
        'key_by_type': 'true'
    }
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 429:
            LogSistema.objects.create(livello='WARNING', azione='Calcolo VAM', messaggio=f"Rate Limit Strava raggiunto (ID: {activity_id})")
            return None
            
        if response.status_code != 200:
            LogSistema.objects.create(livello='ERROR', azione='Calcolo VAM', messaggio=f"Errore streams ({response.status_code}) per ID {activity_id}")
            return None
            
        data = response.json()
        
        if 'grade_smooth' not in data or 'altitude' not in data or 'time' not in data:
            return None
            
        grades = data['grade_smooth']['data']
        altitudes = data['altitude']['data']
        times = data['time']['data']
        
        total_gain = 0
        total_time = 0
        
        # Variabili per il segmento corrente
        current_gain = 0
        current_time = 0
        
        # Iteriamo sui punti. Assumiamo che le liste siano allineate.
        # Partiamo da 1 perché serve il delta rispetto al precedente.
        for i in range(1, len(grades)):
            # Filtro: Pendenza > 7% (Mastra-Logic: Solo salite vere)
            if grades[i] > 7.0:
                delta_h = altitudes[i] - altitudes[i-1]
                delta_t = times[i] - times[i-1]
                
                # Sommiamo solo se c'è guadagno positivo e tempo positivo
                if delta_h > 0 and delta_t > 0:
                    current_gain += delta_h
                    current_time += delta_t
            else:
                # Il segmento si è interrotto (pendenza scesa sotto il 7%)
                # Commit del segmento SOLO se è durato più di 10 minuti (600s)
                # Questo evita che "strappi" brevi falsino la VAM media su lunghe distanze.
                if current_time >= 600:
                    total_gain += current_gain
                    total_time += current_time
                
                # Reset del segmento corrente
                current_gain = 0
                current_time = 0
        
        # Controllo finale se l'attività finisce durante una salita valida
        if current_time >= 600:
            total_gain += current_gain
            total_time += current_time
                    
        if total_time > 0:
            # VAM = (Metri / Secondi) * 3600 -> Metri/Ora
            vam = (total_gain / total_time) * 3600
            return round(vam, 1)
            
        return 0
        
    except Exception as e:
        LogSistema.objects.create(livello='ERROR', azione='Calcolo VAM', messaggio=f"Eccezione ID {activity_id}: {e}")
        return None

def calcola_vo2max_effettivo(attivita, profilo):
    """
    Calcola il VO2max Effettivo (Running Index) basato sull'efficienza (Mastra-Logic).
    Formula: Costo O2 del Passo / % Riserva Cardiaca.
    
    Logica:
    - Se Passo Reale < Passo Atteso (per quel VO2), il punteggio sale (Alta Efficienza).
    - Se Passo Reale > Passo Atteso, il punteggio scende (Bassa Efficienza).
    - Se Dislivello > 50m, usa il GAP (Passo Regolato) per neutralizzare la pendenza.
    """
    # Calcolo solo su strada/corsa come richiesto
    if attivita.tipo_attivita != 'Run':
        return None
        
    # 1. Determina la velocità di calcolo (m/s)
    speed_ms = 0
    # Se c'è dislivello significativo (>50m) e Strava ci dà il GAP, usiamo quello
    if attivita.dislivello > 50 and attivita.gap_passo:
        speed_ms = attivita.gap_passo
    elif attivita.distanza > 0 and attivita.durata > 0:
        speed_ms = attivita.distanza / attivita.durata
            
    if speed_ms <= 0:
        return None
        
    # 2. Costo O2 (Formula ACSM: 0.2 * v_m_min + 3.5)
    speed_m_min = speed_ms * 60
    vo2_cost = (0.2 * speed_m_min) + 3.5
    
    # 3. Intensità (% Riserva Cardiaca)
    hr_max = profilo.fc_massima_teorica or profilo.fc_max
    if not attivita.fc_media or not hr_max or not profilo.fc_riposo:
        return None
        
    hrr = hr_max - profilo.fc_riposo
    if hrr <= 0: return None
    
    intensity = (attivita.fc_media - profilo.fc_riposo) / hrr
    
    # Filtro: Se l'intensità è troppo bassa (<50%), il calcolo non è lineare/affidabile
    if intensity < 0.50:
        return None
        
    # 4. VO2max Effettivo
    return round(vo2_cost / intensity, 2)

def calcola_efficienza(attivita):
    """
    Calcola l'Efficiency Factor (EF) in Metri/Battito.
    Formula: Velocità GAP (m/min) / FC (bpm).
    Indica quanti metri percorri con un singolo battito cardiaco.
    """
    if attivita.tipo_attivita != 'Run' or not attivita.fc_media or attivita.fc_media <= 0:
        return None
    
    # Determina la velocità (m/s) usando GAP se c'è dislivello significativo
    speed_ms = 0
    if attivita.dislivello > 50 and attivita.gap_passo:
        speed_ms = attivita.gap_passo
    elif attivita.distanza > 0 and attivita.durata > 0:
        speed_ms = attivita.distanza / attivita.durata
        
    if speed_ms <= 0:
        return None
        
    speed_m_min = speed_ms * 60
    
    # EF = m/min / bpm = metri/battito
    return round(speed_m_min / attivita.fc_media, 2)

def calcola_metrica_vo2max(attivita, profilo):
    """
    Calcola il VO2max matematico basato sui dati reali di Strava.
    """
    try:
        # 0. Esclusione Manuale (Workout)
        # Se l'utente ha taggato l'attività come "Allenamento" (Workout) su Strava (type 3), la scartiamo a priori.
        # if attivita.workout_type == 3:
        #    return None

        # 1. Preparazione Dati
        distanza_metri = attivita.distanza
        durata_secondi = attivita.durata
        fc_media = attivita.fc_media
        d_plus = attivita.dislivello
        
        # Filtro Passo Lento: Se > 9:30 min/km (570 sec/km), ignoriamo l'attività.
        # Evita che camminate o recuperi abbassino drasticamente la media VO2max.
        if distanza_metri > 0 and durata_secondi > 0:
            passo_sec_km = durata_secondi / (distanza_metri / 1000)
            if passo_sec_km > 570:
                print(f"Passo > 9:30 min/km, calcolo VO2max ignorato.", flush=True)
                return None

        # Parametri Atleta
        hr_max = profilo.fc_massima_teorica
        hr_rest = profilo.fc_riposo # Il campo nel tuo modello è fc_riposo
        
        # Controllo Peso (Default 70kg se mancante)
        peso_atleta = profilo.peso
        if not peso_atleta or peso_atleta <= 0:
            print("Peso non configurato per l'atleta fondamentale impostarlo nel settings stai assumendo un valore di default 70", flush=True)
            peso_atleta = 70.0
        
        # DEBUG: Stampa i valori usati per il calcolo
        print(f"\n--- DEBUG CALCOLO VO2MAX (ID: {getattr(attivita, 'strava_activity_id', 'N/A')}) ---", flush=True)
        print(f"Dati: Dist={distanza_metri}m, Durata={durata_secondi}s, FC_Avg={fc_media}, D+={d_plus}", flush=True)
        print(f"Profilo: HR_Max={hr_max}, HR_Rest={hr_rest}", flush=True)

        if not fc_media or not hr_max or not hr_rest:
            print("Dati insufficienti (FC o Profilo mancanti).", flush=True)
            return None

        is_trail = getattr(attivita, 'tipo_attivita', 'Run') == 'TrailRun'
        is_race = getattr(attivita, 'workout_type', 0) == 1
        
        if is_trail:
            if is_race:
                # LOGICA GARA TRAIL (Allineata a Dashboard)
                # 100m D+ = 500m piani (Coeff 5)
                distanza_equivalente = distanza_metri + (5 * d_plus)
                velocita_eq = distanza_equivalente / (durata_secondi / 60)
                vo2_attivita = (0.2 * velocita_eq) + 3.5
            else:
                # LOGICA TRAIL ALLENAMENTO (Standard)
                # 100m D+ = 500m piani (Coeff 5)
                distanza_equivalente = distanza_metri + (5 * d_plus)
                velocita_eq = distanza_equivalente / (durata_secondi / 60)
                vo2_attivita = (0.2 * velocita_eq) + 3.5
            
        else:
            # LOGICA STRADA (Formula ACSM Modificata: Flat + Efficienza)
            # 1. Normalizzazione al piano (uso GAP se disponibile per simulare pendenza 0%)
            if attivita.gap_passo:
                velocita_m_min = attivita.gap_passo * 60
            else:
                velocita_m_min = distanza_metri / (durata_secondi / 60)
            
            # 2. Formula ACSM per corsa in piano (0.2 * v + 3.5)
            vo2_attivita = (0.2 * velocita_m_min) + 3.5
        
        # 5. Calcolo VO2max (Nuovo Algoritmo 2026 - Revisione)
        
        # --- 2. PROIEZIONE AL MASSIMALE (Karvonen Restore) ---
        # Torniamo a Karvonen (% Riserva) che è più fisiologico e meno pessimistico della % FC Max pura.
        hrr_value = hr_max - hr_rest
        if hrr_value <= 0: return None
        
        percent_hrr = (fc_media - hr_rest) / hrr_value
        
        # Filtro validità (Sforzo minimo 60% Riserva e durata > 20 min)
        if percent_hrr < 0.60 or durata_secondi < 1200:
            print("Sforzo < 60% HRR o Durata < 20min, calcolo ignorato.", flush=True)
            return None
            
        # Formula inversa Karvonen: VO2max = ((VO2_activity - 3.5) / %HRR) + 3.5
        vo2_performance = ((vo2_attivita - 3.5) / percent_hrr) + 3.5

        # --- 3. FATTORE DI EFFICIENZA (Passo Lento) ---
        # Se il passo è più lento di 5:15 min/km (315 s/km = ~190.5 m/min), riduciamo del 5% (era 10%)
        # Ammorbidiamo la penalità per non punire troppo i lenti.
        if not is_trail and velocita_m_min < 190.5:
            vo2_performance *= 0.95
            print(f"Penalità Efficienza 5% applicata (Passo > 5:15)", flush=True)

        # --- 4. TETTO MASSIMO (Ancoraggio ITRA) ---
        # Manteniamo i cap per evitare allucinazioni verso l'alto, ma leggermente più permissivi
        itra_index = profilo.indice_itra
        if itra_index and itra_index > 0:
            if itra_index < 500:
                vo2_performance = min(vo2_performance, 54.0) # Alzato da 52
            elif itra_index < 600:
                vo2_performance = min(vo2_performance, 60.0) # Alzato da 58

        vo2max_stima_trail_strada = vo2_performance
        
        # Calcolo Metriche Aggiuntive (Kcal e VO2 Assoluto) per debug/log
        vo2_assoluto_l_min = (vo2max_stima_trail_strada * peso_atleta) / 1000
        # Formula Kcal Attive: ((vo2_attivita - 3.5) * peso * minuti * 5 kcal/L) / 1000
        kcal_totali = ((vo2_attivita - 3.5) * peso_atleta * (durata_secondi / 60) * 5) / 1000
        print(f"DEBUG EXTRA: VO2 Abs: {vo2_assoluto_l_min:.2f} L/min, Kcal: {kcal_totali:.0f}", flush=True)
        
        # --- AUTO-DETECT RIPETUTE (Heuristic Check) ---
        # Se l'utente dimentica il tag, proviamo a capire se è un interval training.
        # FIRMA RIPETUTE: Alta FC Max (picco) + Alta Variabilità (FC Max - FC Med) + Risultato VO2 basso (causa pause).
        if profilo.vo2max_stima_statistica and attivita.fc_max_sessione:
            # 1. Variabilità: Differenza tra picco e media > 25 bpm (indica pause o variazioni violente)
            hr_variability = attivita.fc_max_sessione - fc_media
            
            # 2. Intensità: Ha spinto? (FC Max > 85% del teorico)
            fc_peak_threshold = profilo.fc_massima_teorica * 0.85
            
            # 3. Performance: Il risultato è crollato? (< 88% della sua media storica)
            vo2_drop_threshold = profilo.vo2max_stima_statistica * 0.88
            
            if (vo2max_stima_trail_strada < vo2_drop_threshold) and (hr_variability > 25) and (attivita.fc_max_sessione > fc_peak_threshold):
                print(f"Auto-Detect Ripetute: ATTIVITÀ SCARTATA. (VO2: {vo2max_stima_trail_strada:.1f} vs Avg {profilo.vo2max_stima_statistica}, Var FC: {hr_variability}bpm)", flush=True)
                return None
        
        print(f"VO2 Attività: {vo2_attivita:.2f} -> VO2max Stimato: {vo2max_stima_trail_strada:.2f}", flush=True)
        
        return round(vo2max_stima_trail_strada, 2)
    except Exception as e:
        print(f"Errore calcolo matematico: {e}", flush=True)
        return None

def stima_vo2max_atleta(profilo):
    """
    Analizza lo storico delle attività per calcolare un VO2max consolidato (Media Mobile).
    Scarta gli outlier e stabilizza il dato.
    """
    # 1. Stima Statistica (Trail + Strada) - Ultime 60 attività valide (Stagionale)
    sessioni_all = Attivita.objects.filter(
        atleta=profilo, 
        vo2max_stimato__isnull=False
    ).order_by('-data')[:60]

    media_vo2_all = None
    if sessioni_all and len(sessioni_all) >= 3:
        valori_all = [s.vo2max_stimato for s in sessioni_all]
        media_vo2_all = sum(valori_all) / len(valori_all)

    # 2. VO2max Solo Strada - Ultime 60 attività SOLO 'Run'
    sessioni_strada = Attivita.objects.filter(
        atleta=profilo,
        tipo_attivita='Run',
        vo2max_stimato__isnull=False
    ).order_by('-data')[:60]

    if sessioni_strada and len(sessioni_strada) >= 3:
        valori_strada = [s.vo2max_stimato for s in sessioni_strada]
        media_vo2_strada = sum(valori_strada) / len(valori_strada)
        profilo.vo2max_strada = round(media_vo2_strada, 1)
    else:
        profilo.vo2max_strada = None

    if media_vo2_all:
        profilo.vo2max_stima_statistica = round(media_vo2_all, 1)
    else:
        profilo.vo2max_stima_statistica = None

    profilo.save()
    
    print(f"DEBUG: VO2max Aggiornato -> Statistica: {profilo.vo2max_stima_statistica}, Strada: {profilo.vo2max_strada}", flush=True)
    return profilo.vo2max_stima_statistica

def calcola_trend_atleta(profilo, cutoff_date=None):
    """
    Calcola il trend (variazione %) delle ultime 5 attività rispetto alle precedenti 15.
    Restituisce un dizionario con le variazioni per ogni metrica.
    """
    # Prendiamo le ultime 20 attività per avere un campione significativo
    qs = Attivita.objects.filter(atleta=profilo)
    if cutoff_date:
        qs = qs.filter(data__lt=cutoff_date)
    qs = qs.order_by('-data')[:20]
    activities = list(qs)
    
    if len(activities) < 5:
        return {} # Dati insufficienti per un trend

    # Split: Recenti (ultime 5) vs Storico (successive 15)
    recenti = activities[:5]
    storico = activities[5:]
    
    if not storico:
        return {}

    trends = {}

    def get_avg(source_list, attr, filter_func=None):
        values = [getattr(a, attr) for a in source_list if getattr(a, attr) is not None and (filter_func(a) if filter_func else True)]
        if not values: return 0
        return sum(values) / len(values)

    def calc_diff(avg_new, avg_old):
        if avg_old == 0: return 0
        return round(((avg_new - avg_old) / avg_old) * 100, 1)

    # 1. VO2max Stimato (Generale)
    trends['vo2max'] = calc_diff(get_avg(recenti, 'vo2max_stimato'), get_avg(storico, 'vo2max_stimato'))
    
    # 2. VO2max Solo Strada (Filtro per tipo 'Run')
    is_run = lambda a: a.tipo_attivita == 'Run'
    trends['vo2max_strada'] = calc_diff(get_avg(recenti, 'vo2max_stimato', is_run), get_avg(storico, 'vo2max_stimato', is_run))
    
    # 3. VAM (Solo se > 0)
    trends['vam'] = calc_diff(get_avg(recenti, 'vam'), get_avg(storico, 'vam'))
    
    # 4. Potenza
    trends['potenza'] = calc_diff(get_avg(recenti, 'potenza_media'), get_avg(storico, 'potenza_media'))
    
    # 5. Volume (Distanza media per sessione)
    trends['distanza'] = calc_diff(get_avg(recenti, 'distanza'), get_avg(storico, 'distanza'))

    # 6. FC Media
    fc_recent = get_avg(recenti, 'fc_media')
    fc_historic = get_avg(storico, 'fc_media')
    trends['fc_media'] = calc_diff(fc_recent, fc_historic)
    trends['fc_media_recent'] = int(fc_recent)
    trends['fc_media_historic'] = int(fc_historic)
    
    # 7. Passo (basato su velocità m/s per correttezza matematica)
    # Nota: Velocità maggiore = Trend positivo (verde).
    def get_avg_speed(source_list):
        speeds = []
        for a in source_list:
            if a.durata > 0: speeds.append(a.distanza / a.durata)
        if not speeds: return 0
        return sum(speeds) / len(speeds)

    trends['passo'] = calc_diff(get_avg_speed(recenti), get_avg_speed(storico))

    return trends

def stima_potenza_watt(distanza, durata, dislivello, peso):
    """
    Stima la Potenza Meccanica (Watt) usando l'equazione di Minetti per il costo energetico su pendenza.
    Output allineato ai valori tipici dei sensori (es. Stryd) assumendo un'efficienza del 25%.
    """
    if durata <= 0 or peso <= 0 or distanza <= 0:
        return None
    
    # 1. Velocità in m/s
    speed_ms = distanza / durata
    
    # 2. Pendenza (frazione, es. 0.10 = 10%)
    grade = dislivello / distanza
    
    # 3. Formula Minetti (Costo Energetico J/kg/m in base alla pendenza)
    # C = 155.4*i^5 - 30.4*i^4 - 43.3*i^3 + 46.3*i^2 + 19.5*i + 3.6
    costo_j_kg_m = (155.4 * grade**5) - (30.4 * grade**4) - (43.3 * grade**3) + (46.3 * grade**2) + (19.5 * grade) + 3.6
    
    # 4. Potenza Metabolica Totale (Watt) = Costo * Velocità * Peso
    # 5. Potenza Meccanica (Watt) = ~25% della Metabolica (Efficienza corsa)
    potenza_stimata = (costo_j_kg_m * speed_ms * peso) * 0.25
    
    return round(potenza_stimata, 1)

def stima_potenziale_gara(profilo):
    """
    Stima la distanza di gara affrontabile basandosi su volume settimanale e lungo massimo degli ultimi 45 giorni.
    """
    end_date = timezone.now()
    start_date = end_date - timedelta(days=45)
    
    qs = Attivita.objects.filter(atleta=profilo, data__gte=start_date)
    
    if not qs.exists():
        return "Non Classificato"
        
    totale_km = qs.aggregate(Sum('distanza'))['distanza__sum'] or 0
    avg_weekly_km = (totale_km / 1000) / (45/7)
    
    lungo_max = qs.aggregate(Max('distanza'))['distanza__max'] or 0
    lungo_max_km = lungo_max / 1000
    
    # Logica di Classificazione (Volume + Lungo)
    if avg_weekly_km >= 60 and lungo_max_km >= 28:
        return "Ultra Marathon 🏔️"
    elif avg_weekly_km >= 40 and lungo_max_km >= 20:
        return "Marathon / 30k 🏃"
    elif avg_weekly_km >= 25 and lungo_max_km >= 14:
        return "Half Marathon 🏁"
    elif avg_weekly_km >= 15 and lungo_max_km >= 8:
        return "10k 👟"
    else:
        return "5k / Base 👶"

def analizza_squadra_coach(context):
    """Genera un report AI per il coach basato sui dati aggregati della settimana."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Errore: Chiave API non trovata."

    client = genai.Client(api_key=api_key)

    # Estrazione dati dal contesto
    week_label = context.get('week_label', 'Settimana corrente')
    vol_km = context.get('vol_current_km', 0)
    trend_vol = context.get('trend_vol', 0)
    inattivi = context.get('atleti_inattivi', [])
    num_inattivi = inattivi.count() if hasattr(inattivi, 'count') else len(inattivi)
    
    top = context.get('top_improvers', [])
    struggling = context.get('struggling', [])
    fc_alerts = context.get('fc_alerts', [])
    acwr_alerts = context.get('acwr_alerts', [])

    prompt = f"""
    Sei il Capo Allenatore di una squadra di corsa. Analizza il report settimanale ({week_label}).
    
    DATI GENERALI:
    - Volume Totale Squadra: {vol_km} km (Trend: {trend_vol}% vs settimana scorsa).
    - Atleti Inattivi (>7gg): {num_inattivi}.

    PERFORMANCE:
    - Top Improvers (VO2max in crescita): {', '.join([f"{x['atleta'].user.first_name} (+{x['trends']['vo2max']}%)" for x in top]) if top else 'Nessuno'}
    - In Calo (VO2max in discesa): {', '.join([f"{x['atleta'].user.first_name} ({x['trends']['vo2max']}%)" for x in struggling]) if struggling else 'Nessuno'}

    ALLARMI FISIOLOGICI:
    - FC in aumento anomalo: {len(fc_alerts)} atleti.
    - Rischio Carico (ACWR): {len(acwr_alerts)} atleti fuori range (Rischio Infortunio > 1.3 o Detraining < 0.6).

    Fornisci un'analisi sintetica e professionale (max 15 righe) per lo staff tecnico.
    1. Valuta lo stato di salute generale della squadra.
    2. Dai indicazioni su come gestire gli atleti in allarme o in calo.
    3. Suggerisci il focus per la prossima settimana basandoti sul volume e sui trend.
    Usa formattazione Markdown per i titoli (## Titolo) e liste puntate.
    """

    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"Errore analisi AI: {e}"

def analizza_performance_atleta(profilo):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Errore: Chiave API non trovata nel file .env."

    # Inizializzazione pulita del client 2026
    client = genai.Client(api_key=api_key)
    
    # 1. Analisi Trend Settimanale (Ultime 3 settimane)
    today = timezone.now()
    # Calcoliamo l'inizio della settimana corrente (Lunedì)
    current_week_start = today - timedelta(days=today.weekday())
    current_week_start = current_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    weeks_summary = []
    for i in range(3):
        # 0 = Corrente, 1 = Scorsa, 2 = Due fa
        start_date = current_week_start - timedelta(weeks=i)
        end_date = start_date + timedelta(days=7)
        
        qs = Attivita.objects.filter(atleta=profilo, data__gte=start_date, data__lt=end_date)
        
        if qs.exists():
            dist = qs.aggregate(Sum('distanza'))['distanza__sum'] / 1000
            elev = qs.aggregate(Sum('dislivello'))['dislivello__sum']
            # Media VO2max (escludendo None)
            vo2_vals = [a.vo2max_stimato for a in qs if a.vo2max_stimato]
            avg_vo2 = sum(vo2_vals)/len(vo2_vals) if vo2_vals else 0
            
            label = "Questa Settimana" if i == 0 else f"Settimana -{i}"
            weeks_summary.append(f"- {label} ({start_date.strftime('%d/%m')}): {dist:.1f}km, {elev:.0f}m D+, VO2max Avg: {avg_vo2:.1f}")
        else:
            weeks_summary.append(f"- Settimana -{i}: Nessuna attività.")

    # 2. Dettaglio Ultime 5 Sessioni
    attivita = Attivita.objects.filter(atleta=profilo).order_by('-data')[:5]
    storico_testo = ""
    for act in attivita:
        tipo = "Trail 🏔️" if act.tipo_attivita == "TrailRun" else "Strada 🛣️"
        storico_testo += f"- {act.data.strftime('%d/%m')} [{tipo}]: {act.distanza/1000:.1f}km, {act.dislivello}m D+, Passo: {act.passo_medio}, FC: {act.fc_media}bpm, VO2: {act.vo2max_stimato}\n"

    prompt = f"""
    Sei un coach esperto di atletica e trail running. Analizza la performance dell'atleta {profilo.user.first_name}.
    
    PROFILO ATLETA:
    - Peso: {profilo.peso}kg, FC Max: {profilo.fc_massima_teorica} bpm, FC Riposo: {profilo.fc_riposo} bpm.
    - VO2max Attuale (Stima): {profilo.vo2max_stima_statistica} ml/kg/min.
    - Indici: ITRA {profilo.indice_itra}, UTMB {profilo.indice_utmb}.

    TREND ULTIME 3 SETTIMANE:
    {chr(10).join(weeks_summary)}

    ULTIME 5 SESSIONI:
    {storico_testo}

    RICHIESTA:
    Fornisci un'analisi dettagliata ma concisa (max 20 righe) su:
    1. **Stato di Forma Attuale**: Come sta andando rispetto alle settimane scorse? È in crescita, stallo o calo?
    2. **Analisi Fisiologica**: Valuta la relazione tra passo, FC e dislivello nelle ultime sessioni.
    3. **Consigli per la Prossima Settimana**: Su cosa concentrarsi (Volume, Intensità o Recupero)?

    Usa formattazione Markdown con titoli in grassetto (es. **Titolo**) o elenchi puntati. Sii motivante ma tecnico.
    """
    
    try:
        # Usiamo il modello più stabile per il piano gratuito nel 2026
        # Se gemini-1.5-pro dà 404, questo è il nome corretto da usare
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"DEBUG ERRORE FINALE: {e}")
        return "⚠️ Servizio AI momentaneamente non disponibile. Riprova tra un minuto."

def processa_attivita_strava(act, profilo, access_token):
    """
    Logica centralizzata per salvare/aggiornare un'attività Strava nel DB.
    Restituisce (Attivita, created).
    """
    # 0. Filtro Privacy: Ignoriamo attività private SE l'utente non ha abilitato l'import
    if act.get('private') and not profilo.importa_attivita_private:
        # Logica di sicurezza: Se l'utente non vuole importare le private, le scartiamo silenziosamente.
        # Questo previene l'importazione indesiderata se il token ha permessi ampi (activity:read_all).
        return None, False

    # 1. Tipo Attività
    strava_sport_type = act.get('sport_type') or act.get('type')
    if strava_sport_type in ['TrailRun', 'Hike']:
        tipo_finale = 'TrailRun'
    else:
        tipo_finale = 'Run'

    # 2. Calcolo Potenza (Fallback)
    watts = act.get('average_watts')
    if not watts and profilo.peso:
        watts = stima_potenza_watt(act['distance'], act['moving_time'], act.get('total_elevation_gain', 0), profilo.peso)

    # 3. Salvataggio
    nuova_attivita, created = Attivita.objects.update_or_create(
        strava_activity_id=act['id'],
        defaults={
            'atleta': profilo,
            'nome': act.get('name'),
            'workout_type': act.get('workout_type'),
            'data': act['start_date'],
            'distanza': act['distance'],
            'durata': act['moving_time'],
            'dislivello': act.get('total_elevation_gain', 0),
            'fc_media': act.get('average_heartrate'),
            'fc_max_sessione': act.get('max_heartrate'),
            'passo_medio': formatta_passo(act.get('average_speed', 0)),
            'cadenza_media': act.get('average_cadence'),
            'sforzo_relativo': act.get('suffer_score'),
            'potenza_media': watts,
            'gap_passo': act.get('average_grade_adjusted_speed'),
            'tipo_attivita': tipo_finale,
        }
    )
    
    # 4. Calcolo VO2max
    nuova_attivita.vo2max_stimato = calcola_metrica_vo2max(nuova_attivita, profilo)
    
    # 5. Calcolo VAM Selettiva (Solo per TrailRun significativi)
    if nuova_attivita.tipo_attivita == 'TrailRun' and nuova_attivita.dislivello > 150:
        # Lo calcoliamo se è nuova o se non ce l'ha ancora
        if created or nuova_attivita.vam_selettiva is None:
            # Piccola pausa per rate limit se stiamo processando tante attività
            # Ma qui siamo in una funzione singola, la gestione del rate limit massivo va fuori
            vam_sel = calcola_vam_selettiva(act['id'], access_token)
            if vam_sel and vam_sel > 0:
                nuova_attivita.vam_selettiva = vam_sel

    # 6. Recupero Dispositivo (Solo per NUOVE attività per risparmiare API)
    # Il campo 'device_name' è presente solo nel dettaglio attività, non nel summary.
    if created and access_token:
        try:
            url_detail = f"https://www.strava.com/api/v3/activities/{act['id']}"
            # Timeout breve per non bloccare il sync
            resp_detail = requests.get(url_detail, headers={'Authorization': f'Bearer {access_token}'}, timeout=5)
            if resp_detail.status_code == 200:
                detail_data = resp_detail.json()
                device_name = detail_data.get('device_name')
                if device_name:
                    nuova_attivita.dispositivo = device_name
                    nuova_attivita.save(update_fields=['dispositivo'])
        except Exception as e:
            print(f"Warning: Impossibile recuperare dispositivo per {act['id']}: {e}", flush=True)

    if created:
        LogSistema.objects.create(livello='INFO', azione='Import Attività', utente=profilo.user, messaggio=f"Nuova attività: {nuova_attivita.nome} ({nuova_attivita.tipo_attivita})")
    else:
        # Logghiamo solo se aggiorniamo qualcosa di importante o per debug, qui evito per non intasare se non richiesto
        pass

    nuova_attivita.save()
    return nuova_attivita, created

def fix_strava_duplicates():
    """
    Rileva e rimuove configurazioni Strava duplicate che causano errori 500.
    """
    try:
        # Usa iexact per case-insensitive matching (es. 'Strava' vs 'strava')
        apps = SocialApp.objects.filter(provider__iexact='strava')
        
        # 1. Gestione Duplicati
        if apps.count() > 1:
            print(f"FIX: Trovate {apps.count()} app Strava. Pulizia in corso...", flush=True)
            first_app = apps.order_by('id').first()
            from allauth.socialaccount.models import SocialToken
            for app in apps.exclude(id=first_app.id):
                print(f"FIX: Rimozione app duplicata ID {app.id}", flush=True)
                for token in SocialToken.objects.filter(app=app):
                    if not SocialToken.objects.filter(app=first_app, account=token.account).exists():
                        token.app = first_app
                        token.save()
                app.delete()
            print("FIX: Pulizia completata.", flush=True)
            
        # 2. Gestione Mancanza (DoesNotExist) - Creazione Automatica
        elif apps.count() == 0:
            client_id = os.environ.get('STRAVA_CLIENT_ID')
            secret = os.environ.get('STRAVA_CLIENT_SECRET')
            
            if client_id and secret:
                print("FIX: App Strava mancante. Tentativo di creazione automatica...", flush=True)
                from django.contrib.sites.models import Site
                # Assicuriamoci che esista un sito (ID=1 è il default di Django)
                site, _ = Site.objects.get_or_create(id=1, defaults={'domain': 'localhost', 'name': 'localhost'})
                
                app = SocialApp.objects.create(provider='strava', name='Strava', client_id=client_id, secret=secret)
                app.sites.add(site)
                print(f"FIX: App Strava creata e associata al sito {site.name} (ID: {site.id})", flush=True)
            else:
                print("FIX: App Strava mancante ma credenziali ENV non trovate.", flush=True)

    except Exception as e:
        print(f"Errore fix_strava_duplicates: {e}", flush=True)

BRAND_LOGOS = {
    'Nike': 'https://upload.wikimedia.org/wikipedia/commons/a/a6/Logo_NIKE.svg',
    'Hoka': 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/51/Hoka_One_One_Logo.svg/1200px-Hoka_One_One_Logo.svg.png',
    'Adidas': 'https://upload.wikimedia.org/wikipedia/commons/2/20/Adidas_Logo.svg',
    'Saucony': 'https://upload.wikimedia.org/wikipedia/commons/dd/Saucony_Logo.svg',
    'Brooks': 'https://upload.wikimedia.org/wikipedia/commons/b/b5/Brooks_Sports_logo.svg',
    'Asics': 'https://upload.wikimedia.org/wikipedia/commons/b/b1/Asics_Logo.svg',
    'New Balance': 'https://upload.wikimedia.org/wikipedia/commons/e/ea/New_Balance_logo.svg',
    'La Sportiva': 'https://upload.wikimedia.org/wikipedia/commons/3/3a/La_Sportiva_logo.svg',
    'Salomon': 'https://upload.wikimedia.org/wikipedia/commons/6/6b/Salomon_Sports_Logo.svg',
    'Altra': 'https://upload.wikimedia.org/wikipedia/commons/6/68/Altra_Running_Logo.svg',
    'Scarpa': 'https://upload.wikimedia.org/wikipedia/commons/0/02/SCARPA_logo.svg',
    'The North Face': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/The_North_Face_logo.svg/1200px-The_North_Face_logo.svg.png',
    'Nnormal': 'https://nnormal.com/cdn/shop/files/logo_nnormal_black.svg?v=1663578888&width=150',
    'Mizuno': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/cb/Mizuno_Logo.svg/1200px-Mizuno_Logo.svg.png',
    'Puma': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Puma-logo.svg/1200px-Puma-logo.svg.png',
    'Craft': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0d/Craft_Sportswear_Logo.svg/1200px-Craft_Sportswear_Logo.svg.png',
    'Inov-8': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Inov-8_logo.svg/1200px-Inov-8_logo.svg.png',
    'Vibram': 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Vibram_logo.svg/1200px-Vibram_logo.svg.png',
    'Scott': 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/Scott_Sports_logo.svg/1200px-Scott_Sports_logo.svg.png',
    'Topo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Topo_Athletic_logo.png/800px-Topo_Athletic_logo.png',
    'Kiprun': 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/53/Kiprun_logo.svg/1200px-Kiprun_logo.svg.png',
}

def normalizza_scarpa(nome):
    """
    Tenta di estrarre Brand e Modello dal nome della scarpa su Strava.
    """
    nome_lower = nome.lower()
    brands = {
        'Nike': ['nike', 'pegasus', 'vaporfly', 'alphafly', 'zoom', 'terra kiger', 'wildhorse', 'invincible', 'vomero'],
        'Hoka': ['hoka', 'one one', 'clifton', 'speedgoat', 'bondi', 'mach', 'challenger', 'mafate', 'tecton', 'zinal'],
        'Adidas': ['adidas', 'adizero', 'boston', 'terrex', 'agravic'],
        'Saucony': ['saucony', 'peregrine', 'kinvara', 'ride', 'endorphin', 'triumph', 'guide', 'xodus'],
        'Brooks': ['brooks', 'ghost', 'glycerin', 'cascadia', 'catamount', 'caldera', 'hyperion'],
        'Asics': ['asics', 'novablast', 'metaspeed', 'gel-kayano', 'kayano', 'nimbus', 'trabuco', 'cumulus'],
        'New Balance': ['new balance', 'nb', 'hierro', '1080', 'rebel', 'more v'],
        'La Sportiva': ['la sportiva', 'bushido', 'jackal', 'cyklon', 'helios', 'mutant', 'akasha', 'kaptiva'],
        'Salomon': ['salomon', 'speedcross', 'sense', 'slab', 's-lab', 'pulsar', 'genesis', 'ultra glide'],
        'Altra': ['altra', 'lone peak', 'olympus', 'timp', 'mont blanc', 'superior'],
        'Scarpa': ['scarpa', 'spin', 'ribelle', 'golden gate'],
        'Nnormal': ['nnormal', 'kjerag', 'tomir'],
        'Dynafit': ['dynafit', 'ultra', 'feline'],
        'The North Face': ['north face', 'vectiv', 'flight', 'enduris'],
        'On': ['on running', 'cloud'],
        'Puma': ['puma', 'nitro'],
        'Mizuno': ['mizuno', 'wave'],
        'Craft': ['craft'],
        'Inov-8': ['inov', 'inov8'],
        'Topo': ['topo athletic', 'topo'],
        'Vibram': ['vibram', 'fivefingers'],
        'Kiprun': ['kiprun', 'decathlon', 'evadict'],
        'Scott': ['scott', 'kinabalu', 'supertrac'],
    }
    
    detected_brand = "Altro"
    
    # 1. Rilevamento Brand
    for brand_key, keywords in brands.items():
        for kw in keywords:
            if kw in nome_lower:
                detected_brand = brand_key
                break
        if detected_brand != "Altro":
            break
            
    # 2. Normalizzazione Modello
    modello_clean = nome_lower
    if detected_brand != "Altro":
        # Rimuovi il brand dal nome
        modello_clean = modello_clean.replace(detected_brand.lower(), '')
    
    # FIX: Normalizzazione avanzata per raggruppare paia e versioni (es. "Prodigio V2" -> "Prodigio")
    # 0. Normalizza spazi (rimuove doppi spazi e spazi iniziali/finali)
    modello_clean = " ".join(modello_clean.split())

    # 1. Rimuovi suffissi specifici (ii, iii, iv) ma NON "slab" o "sl" (es. Evo SL)
    modello_clean = re.sub(r'\b(ii|iii|iv)\b', '', modello_clean)

    # 2a. Rimuovi "v." seguito da numero (es. "Prodigio v.2" -> "Prodigio") - Caso specifico "Paio"
    modello_clean = re.sub(r'\bv\.\s*\d+', '', modello_clean)

    # 2b. Rimuovi solo prefisso "v" se seguito da numero (es. "Boston v13" -> "Boston 13") - Caso "Versione"
    modello_clean = re.sub(r'\bv\s*(?=\d)', '', modello_clean)

    # Rimuovi parole comuni e caratteri speciali
    # FIX: Aggiunto \. per preservare versioni decimali come "2.0"
    modello_clean = re.sub(r'[^a-z0-9\s\.]', '', modello_clean) # Solo lettere, numeri e punti
    
    # Rimuovi punti residui ai bordi
    modello_clean = modello_clean.strip('.')

    stopwords = ['scarpe', 'shoes', 'running', 'trail', 'goretex', 'gtx', 'mens', 'womens', 'uomo', 'donna', 'one one']
    for word in stopwords:
        modello_clean = modello_clean.replace(word, '')
        
    # 3. Normalizza spazi di nuovo prima del taglio finale
    modello_clean = " ".join(modello_clean.split())

    # 4. (RIMOSSO) Non rimuoviamo più i numeri finali (es. "Ride 17" resta "Ride 17")
        
    # Prendi le prime 2-3 parole significative
    words = modello_clean.split()
    if words:
        detected_model = " ".join(words[:3]).title()
    else:
        detected_model = nome # Fallback se abbiamo cancellato tutto
        
    return detected_brand, detected_model

def normalizza_dispositivo(nome_device):
    """
    Estrae il Brand dal nome del dispositivo (es. 'Garmin Forerunner 245' -> 'Garmin').
    """
    if not nome_device:
        return "Sconosciuto", "Sconosciuto"
        
    nome_lower = nome_device.lower()
    
    brands_map = {
        'Garmin': ['garmin'],
        'Apple': ['apple', 'watch'],
        'Suunto': ['suunto'],
        'Polar': ['polar'],
        'Coros': ['coros'],
        'Wahoo': ['wahoo', 'elemnt'],
        'Zwift': ['zwift'],
        'Bryton': ['bryton'],
        'Huawei': ['huawei'],
        'Samsung': ['samsung', 'galaxy watch'],
        'Amazfit': ['amazfit', 'zepp'],
    }
    
    for brand, keywords in brands_map.items():
        if any(k in nome_lower for k in keywords):
            return brand, nome_device
            
    return "Altro", nome_device

def analizza_gare_atleta(profilo):
    """Genera un'analisi AI specifica per le gare dell'atleta."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Errore: Chiave API non trovata."
    
    client = genai.Client(api_key=api_key)
    
    # Recuperiamo le gare in ordine cronologico
    gare = Attivita.objects.filter(atleta=profilo, workout_type=1).order_by('data')
    
    if not gare.exists():
        return "Non hai ancora registrato gare. Tagga le tue attività come 'Gara' su Strava per ricevere un'analisi."

    gare_summary = []
    for g in gare:
        pos = f"{g.piazzamento}° assoluto" if g.piazzamento else "Piazzamento non inserito"
        gare_summary.append(f"- {g.data.strftime('%d/%m/%Y')} | {g.nome} | {g.distanza_km}km | {g.dislivello}m D+ | Tempo: {g.durata_formattata} | {pos}")
    
    prompt = f"""
    Sei un analista sportivo e coach di endurance. Analizza la carriera agonistica di {profilo.user.first_name}.
    
    STORICO GARE (Ordine Cronologico):
    {chr(10).join(gare_summary)}
    
    RICHIESTA:
    1. **Analisi Trend**: L'atleta sta migliorando? Come gestisce distanze e dislivelli diversi?
    2. **Valutazione Piazzamenti**: Se presenti, analizza la costanza nei risultati.
    3. **Punti di Forza/Debolezza**: Cosa emerge dai dati (es. va meglio su gare corte/veloci o lunghe/dure)?
    4. **Consiglio Strategico**: Su cosa lavorare per la prossima stagione.
    
    Sii sintetico, motivante e professionale. Usa formattazione Markdown.
    """
    
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"Errore analisi AI: {e}"

def genera_commenti_podio_ai(podio_atleti):
    """
    Genera commenti motivazionali brevi per i 3 atleti a podio usando Gemini.
    Restituisce un dizionario {username: commento}.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {}

    client = genai.Client(api_key=api_key)
    
    lines = []
    for p in podio_atleti:
        lines.append(f"User: {p.user.username} | Nome: {p.user.first_name} | {p.km_week} km | {p.dplus_week} m D+ | Score: {p.punteggio_podio}")

    prompt = f"""
    Sei un commentatore sportivo tecnico ma simpatico. Analizza le performance settimanali di questi 3 atleti sul podio:
    
    {chr(10).join(lines)}
    
    Per ognuno, scrivi UNA sola frase (max 20 parole) che spieghi il motivo del successo (es. "Volume mostruoso", "Dislivello da capra", "Intensità alta").
    Usa un tono vario: epico per il primo, analitico per il secondo, incoraggiante per il terzo. Usa emoji.
    
    Rispondi ESCLUSIVAMENTE con un JSON valido formato così:
    {{
        "username_atleta_1": "Frase...",
        "username_atleta_2": "Frase..."
    }}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Errore AI Podio: {e}")
        return {}

def get_atleti_con_statistiche_settimanali():
    """
    Calcola le statistiche settimanali e il podio per tutti gli atleti.
    Restituisce: (atleti_list, active_atleti_list, podio_list)
    """
    from .models import ProfiloAtleta # Import locale per evitare cicli
    
    today = timezone.now()
    start_week = today - timedelta(days=today.weekday())
    start_week = start_week.replace(hour=0, minute=0, second=0, microsecond=0)

    atleti_qs = ProfiloAtleta.objects.select_related('user').exclude(user__username='mastra').annotate(
        ultima_corsa=Max('sessioni__data'),
        km_week_raw=Sum('sessioni__distanza', filter=Q(sessioni__data__gte=start_week)),
        dplus_week_raw=Sum('sessioni__dislivello', filter=Q(sessioni__data__gte=start_week)),
        fc_avg_week=Avg('sessioni__fc_media', filter=Q(sessioni__data__gte=start_week))
    ).order_by('-vo2max_stima_statistica')
    
    atleti = []
    active_atleti = []
    
    for a in atleti_qs:
        a.km_week = round((a.km_week_raw or 0) / 1000, 1)
        a.dplus_week = int(a.dplus_week_raw or 0)
        atleti.append(a)
        
        if a.km_week > 0 or a.dplus_week > 0:
            # Calcolo Punteggio Podio
            km_sforzo = a.km_week + (a.dplus_week / 100)
            
            intensity_multiplier = 1.0
            intensity_label = "Fondo"
            
            if a.fc_avg_week and a.fc_massima_teorica and a.fc_riposo:
                hrr = a.fc_massima_teorica - a.fc_riposo
                if hrr > 0:
                    intensity_pct = (a.fc_avg_week - a.fc_riposo) / hrr
                    
                    if intensity_pct >= 0.85:
                        intensity_multiplier = 1.5
                        intensity_label = "Alta Intensità (Z4/Z5)"
                    elif intensity_pct >= 0.75:
                        intensity_multiplier = 1.3
                        intensity_label = "Medio/Soglia (Z3/Z4)"
                    elif intensity_pct >= 0.60:
                        intensity_multiplier = 1.1
                        intensity_label = "Fondo Aerobico (Z2)"
                    else:
                        intensity_multiplier = 0.95
                        intensity_label = "Recupero (Z1)"
            
            a.punteggio_podio = round(km_sforzo * intensity_multiplier, 1)
            
            # Motivazione Algoritmica (Fallback)
            if intensity_multiplier >= 1.3:
                a.motivazione_podio = f"Qualità & Quantità! 🚀 {a.km_week}km a {intensity_label}."
            elif a.dplus_week > 1000:
                 a.motivazione_podio = f"Scalatore puro! 🐐 {a.dplus_week}m D+ portati a casa."
            elif a.km_week > 50:
                a.motivazione_podio = f"Macinatore di km! 🏃‍♂️ {a.km_week}km di volume solido."
            else:
                a.motivazione_podio = f"Settimana bilanciata: {a.km_week}km con {a.dplus_week}m D+."
                
            active_atleti.append(a)

    podio = sorted(active_atleti, key=lambda x: x.punteggio_podio, reverse=True)[:3]
    
    return atleti, active_atleti, podio