from google import genai
import requests
import os
from .models import Attivita, ProfiloAtleta, LogSistema
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Max
from allauth.socialaccount.models import SocialApp


def formatta_passo(velocita_ms):
    """Converte velocità m/s in passo min/km (es. 5:30)"""
    if velocita_ms > 0:
        secondi_al_km = 1000 / (velocita_ms * 60)
        minuti = int(secondi_al_km)
        secondi = int((secondi_al_km - minuti) * 60)
        return f"{minuti}:{secondi:02d}"
    return "0:00"

def refresh_strava_token(token_obj, buffer_minutes=10):
    """
    Controlla se il token è scaduto e lo rinnova usando il refresh_token.
    Restituisce il token valido (stringa) o None se fallisce.
    buffer_minutes: Minuti di anticipo con cui rinnovare il token (default 10).
    """
    # Se il token scade tra meno di buffer_minutes (o è già scaduto), lo rinnoviamo
    if token_obj.expires_at and token_obj.expires_at > timezone.now() + timedelta(minutes=buffer_minutes):
        return token_obj.token

    if not token_obj.token_secret:
        LogSistema.objects.create(livello='ERROR', azione='Token Refresh', utente=token_obj.account.user, messaggio="Refresh Token mancante. Necessario nuovo login.")
        return None

    LogSistema.objects.create(livello='INFO', azione='Token Refresh', utente=token_obj.account.user, messaggio="Token scaduto. Tento rinnovo...")
    
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
            LogSistema.objects.create(livello='INFO', azione='Token Refresh', utente=token_obj.account.user, messaggio="Token Strava rinnovato con successo.")
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
        
        # Iteriamo sui punti. Assumiamo che le liste siano allineate.
        # Partiamo da 1 perché serve il delta rispetto al precedente.
        for i in range(1, len(grades)):
            # Filtro: Pendenza > 7%
            if grades[i] > 7.0:
                delta_h = altitudes[i] - altitudes[i-1]
                delta_t = times[i] - times[i-1]
                
                # Sommiamo solo se c'è guadagno positivo e tempo positivo
                if delta_h > 0 and delta_t > 0:
                    total_gain += delta_h
                    total_time += delta_t
                    
        if total_time > 0:
            # VAM = (Metri / Secondi) * 3600 -> Metri/Ora
            vam = (total_gain / total_time) * 3600
            return round(vam, 1)
            
        return 0
        
    except Exception as e:
        LogSistema.objects.create(livello='ERROR', azione='Calcolo VAM', messaggio=f"Eccezione ID {activity_id}: {e}")
        return None

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
                # 100m D+ = 500m piani (Coeff 5) | Fattore Terreno: +5%
                distanza_equivalente = distanza_metri + (5 * d_plus)
                velocita_eq = distanza_equivalente / (durata_secondi / 60)
                vo2_attivita = (0.2 * velocita_eq * 1.05) + 3.5
            else:
                # LOGICA TRAIL ALLENAMENTO (Standard)
                # 100m D+ = 500m piani (Coeff 5) | Fattore Terreno: +5%
                distanza_equivalente = distanza_metri + (5 * d_plus)
                velocita_eq = distanza_equivalente / (durata_secondi / 60)
                vo2_attivita = (0.2 * velocita_eq * 1.05) + 3.5
            
        else:
            # LOGICA STRADA (Formula ACSM Standard)
            # Più precisa per l'asfalto: Costo Orizzontale + Costo Verticale Standard
            velocita_m_min = distanza_metri / (durata_secondi / 60)
            pendenza = d_plus / distanza_metri if distanza_metri > 0 else 0
            
            # 0.2 * v (Orizzontale) + 0.9 * v * pendenza (Verticale) + 3.5 (Basale)
            vo2_attivita = (0.2 * velocita_m_min) + (0.9 * velocita_m_min * pendenza) + 3.5
        
        # 5. Calcolo VO2max
        # Metodo 1: Prestazione (VO2 attività / % Riserva Cardiaca)
        # Se HR_rest scende, %HRR sale, quindi questo valore scende (corretto matematicamente per la singola seduta)
        karvonen_percent = (fc_media - hr_rest) / (hr_max - hr_rest)
        
        if karvonen_percent < 0.60 or durata_secondi < 1200:
            print("Sforzo < 65% o Durata < 20min, calcolo ignorato.", flush=True)
            return None
            
        vo2_performance = vo2_attivita / karvonen_percent

        # Metodo 2: Fisiologia Pura (Uth-Sørensen-Overgaard-Pedersen)
        # VO2max = 15 * (HRmax / HRrest). Questo SALE se HRrest scende.
        vo2_fisiologico = 15.3 * (hr_max / hr_rest)
        
        # Mix Ponderato: 70% Prestazione Reale (quello che hai fatto), 30% Potenziale Fisiologico (chi sei)
        # Questo stabilizza il dato e fa sì che se HRrest scende, il bonus fisiologico compensi il calcolo Karvonen.
        vo2max_stima_trail_strada = (vo2_performance * 0.70) + (vo2_fisiologico * 0.30)
        
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

    if sessioni_all and len(sessioni_all) >= 3:
        valori_all = [s.vo2max_stimato for s in sessioni_all]
        media_vo2_all = sum(valori_all) / len(valori_all)
        profilo.vo2max_stima_statistica = round(media_vo2_all, 1)
    else:
        profilo.vo2max_stima_statistica = None

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
        
    # Rimuovi parole comuni e caratteri speciali
    import re
    modello_clean = re.sub(r'[^a-z0-9\s]', '', modello_clean) # Solo lettere e numeri
    stopwords = ['scarpe', 'shoes', 'running', 'trail', 'goretex', 'gtx', 'mens', 'womens', 'uomo', 'donna', 'one one']
    for word in stopwords:
        modello_clean = modello_clean.replace(word, '')
        
    # Prendi le prime 2-3 parole significative
    words = modello_clean.split()
    if words:
        detected_model = " ".join(words[:3]).title()
    else:
        detected_model = nome # Fallback se abbiamo cancellato tutto
        
    return detected_brand, detected_model