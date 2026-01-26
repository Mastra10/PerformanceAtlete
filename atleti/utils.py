from google import genai
import requests
import os
from .models import Attivita, ProfiloAtleta
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Max


def formatta_passo(velocita_ms):
    """Converte velocità m/s in passo min/km (es. 5:30)"""
    if velocita_ms > 0:
        secondi_al_km = 1000 / (velocita_ms * 60)
        minuti = int(secondi_al_km)
        secondi = int((secondi_al_km - minuti) * 60)
        return f"{minuti}:{secondi:02d}"
    return "0:00"

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
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 429:
            print("Rate Limit Strava raggiunto durante calcolo VAM.")
            return None
            
        if response.status_code != 200:
            print(f"Errore streams Strava ({response.status_code}) per attività {activity_id}")
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
            print(f"DEBUG: VAM Selettiva calcolata: {int(vam)} m/h (su {total_gain}m d+)", flush=True)
            return round(vam, 1)
            
        return 0
        
    except Exception as e:
        print(f"Errore calcolo VAM Selettiva: {e}", flush=True)
        return None

def calcola_metrica_vo2max(attivita, profilo):
    """
    Calcola il VO2max matematico basato sui dati reali di Strava.
    """
    try:
        # 1. Preparazione Dati
        distanza_metri = attivita.distanza
        durata_secondi = attivita.durata
        fc_media = attivita.fc_media
        d_plus = attivita.dislivello
        
        # Parametri Atleta
        hr_max = profilo.fc_massima_teorica
        hr_rest = profilo.fc_riposo # Il campo nel tuo modello è fc_riposo
        
        # DEBUG: Stampa i valori usati per il calcolo
        print(f"\n--- DEBUG CALCOLO VO2MAX (ID: {getattr(attivita, 'strava_activity_id', 'N/A')}) ---", flush=True)
        print(f"Dati: Dist={distanza_metri}m, Durata={durata_secondi}s, FC_Avg={fc_media}, D+={d_plus}", flush=True)
        print(f"Profilo: HR_Max={hr_max}, HR_Rest={hr_rest}", flush=True)

        if not fc_media or not hr_max or not hr_rest:
            print("Dati insufficienti (FC o Profilo mancanti).", flush=True)
            return None

        is_trail = getattr(attivita, 'tipo_attivita', 'Run') == 'TrailRun'
        
        if is_trail:
            # LOGICA TRAIL (Km-Effort Rule)
            # Nel trail, 100m di D+ equivalgono a circa 600m di sforzo in piano (coefficiente 6)
            distanza_equivalente = distanza_metri + (6 * d_plus)
            velocita_eq = distanza_equivalente / (durata_secondi / 60)
            
            # Fattore Terreno: +10% costo ossigeno per instabilità
            vo2_attivita = (0.2 * velocita_eq * 1.10) + 3.5
            
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
    # 1. Stima Statistica (Trail + Strada) - Ultime 30 attività valide
    sessioni_all = Attivita.objects.filter(
        atleta=profilo, 
        vo2max_stimato__isnull=False
    ).order_by('-data')[:30]

    if sessioni_all and len(sessioni_all) >= 3:
        valori_all = [s.vo2max_stimato for s in sessioni_all]
        media_vo2_all = sum(valori_all) / len(valori_all)
        profilo.vo2max_stima_statistica = round(media_vo2_all, 1)
    else:
        profilo.vo2max_stima_statistica = None

    # 2. VO2max Solo Strada - Ultime 30 attività SOLO 'Run'
    sessioni_strada = Attivita.objects.filter(
        atleta=profilo,
        tipo_attivita='Run',
        vo2max_stimato__isnull=False
    ).order_by('-data')[:30]

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
    trends['fc_media'] = calc_diff(get_avg(recenti, 'fc_media'), get_avg(storico, 'fc_media'))
    
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
    vo2_alerts = context.get('vo2_alerts', [])

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
    - Crollo Efficienza (VO2max): {len(vo2_alerts)} atleti.

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
    
    # Preparazione dati per l'analisi (VO2max 65-69 e No Alcohol)
    attivita = Attivita.objects.filter(atleta=profilo).order_by('-data')[:10]
    
    storico_testo = ""
    for act in attivita:
        # Specifichiamo se è Strada o Trail e aggiungiamo il D+
        tipo = "Trail 🏔️" if act.tipo_attivita == "TrailRun" else "Strada 🛣️"
        storico_testo += f"- {act.data} [{tipo}]: {act.distanza}m, Passo: {act.passo_medio}, FC Media: {act.fc_media}bpm, D+: {act.dislivello}m\n"

    prompt = f"""
    Sei un coach esperto. Analizza la performance di un atleta d'élite.
    DATI FISIOLOGICI:
    - Peso: {profilo.peso}kg, FC Max: {profilo.fc_massima_teorica}bpm, FC Riposo: {profilo.battito_riposo}bpm.
    - Storico VO2max: 65-69 ml/kg/min.

    SESSIONI RECENTI:
    {storico_testo}

    ISTRUZIONI:
    1. Calcola il carico di lavoro differenziando tra corse su strada e Trail. 
    2. Tieni conto del dislivello (D+) per valutare l'efficienza aerobica nei trail: un passo lento con alto D+ non indica scarsa forma.
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