import os
import django

# Configura l'ambiente Django (Sostituisci 'config.settings' se diverso)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') 
django.setup()

from squadra_calcio.models import Risultato

calendario = [
    # ==========================================
    # CALENDARIO UNDER 14 (2013) - PDF Ufficiale
    # ==========================================
    {"cat": "2013/2014", "giornata": 1, "data": "2026-10-03", "ora": "15:00", "casa": "FRAORE", "ospite": "VIGATTO"},
    {"cat": "2013/2014", "giornata": 2, "data": "2026-10-10", "ora": None, "casa": "CUS PARMA", "ospite": "FRAORE"},
    {"cat": "2013/2014", "giornata": 3, "data": "2026-10-17", "ora": "15:00", "casa": "FRAORE", "ospite": "BEDONIESE"},
    {"cat": "2013/2014", "giornata": 4, "data": "2026-10-24", "ora": None, "casa": "VIGATTO", "ospite": "FRAORE"},
    {"cat": "2013/2014", "giornata": 5, "data": "2026-10-31", "ora": "15:00", "casa": "FRAORE", "ospite": "LANGHIRANESE"},
    {"cat": "2013/2014", "giornata": 6, "data": "2026-11-07", "ora": "15:00", "casa": "CIRCOLO INZANI", "ospite": "FRAORE"},
    {"cat": "2013/2014", "giornata": 7, "data": "2026-11-14", "ora": "15:00", "casa": "FRAORE", "ospite": "ALSENO"},
    {"cat": "2013/2014", "giornata": 8, "data": "2026-11-21", "ora": None, "casa": "FELEGARESE", "ospite": "FRAORE"},
    {"cat": "2013/2014", "giornata": 9, "data": "2026-11-28", "ora": "15:00", "casa": "FRAORE", "ospite": "SAN LEO"},
    {"cat": "2013/2014", "giornata": 10, "data": "2026-12-05", "ora": "15:00", "casa": "FRAORE", "ospite": "POLISPORTIVA IL CERVO"},
    {"cat": "2013/2014", "giornata": 11, "data": "2026-12-13", "ora": "10:30", "casa": "TEAM TRAVERSETOLO", "ospite": "FRAORE"},

    # ==========================================
    # CALENDARIO UNDER 15-16 (2011/2012) - PDF Ufficiale
    # ==========================================
    {"cat": "2011/2012", "giornata": 2, "data": "2026-10-10", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "ASTRA 2012"},
    {"cat": "2011/2012", "giornata": 3, "data": "2026-10-18", "ora": "10:00", "casa": "BORGO SAN DONNINO", "ospite": "FRAORE 2011"},
    {"cat": "2011/2012", "giornata": 4, "data": "2026-10-24", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "ASTRA 2011"},
    {"cat": "2011/2012", "giornata": 5, "data": "2026-10-31", "ora": None, "casa": "ORATORIO MAFFEI", "ospite": "FRAORE 2011"},
    {"cat": "2011/2012", "giornata": 6, "data": "2026-11-07", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "GS FELINO"},
    {"cat": "2011/2012", "giornata": 7, "data": "2026-11-14", "ora": "16:30", "casa": "CIRCOLO INZANI", "ospite": "FRAORE 2011"},
    {"cat": "2011/2012", "giornata": 8, "data": "2026-11-21", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "CIRCOLO INZANI"},
    {"cat": "2011/2012", "giornata": 9, "data": "2026-11-27", "ora": "19:00", "casa": "OR.SA/LA GRANDE", "ospite": "FRAORE 2011"},
    {"cat": "2011/2012", "giornata": 10, "data": "2026-12-05", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "SAN SECONDO"},
    {"cat": "2011/2012", "giornata": 11, "data": "2026-12-12", "ora": "16:30", "casa": "MILAN CLUB PARMA", "ospite": "FRAORE 2011"},
    {"cat": "2011/2012", "giornata": 12, "data": "2026-12-19", "ora": "15:00", "casa": "FRAORE 2011", "ospite": "CUS PARMA"},
    {"cat": "2011/2012", "giornata": 13, "data": "2027-01-23", "ora": "15:00", "casa": "ORATORIO MAFFEI CASALMAGGIORE", "ospite": "FRAORE 2011"},
]

print("⏳ Pulizia calendario non convalidato...")
Risultato.objects.filter(convalidata=False).delete()

print("⏳ Importazione calendario con orari...")
aggiunte = 0

for match in calendario:
    in_casa = 'FRAORE' in match['casa'].upper()
    avversario = match['ospite'] if in_casa else match['casa']
    avversario = avversario.replace(' 2011', '').replace(' 2012', '').strip()
    
    Risultato.objects.create(
        categoria=match['cat'],
        data_partita=match['data'],
        orario=match['ora'],
        avversario=avversario,
        giornata=match['giornata'],
        in_casa=in_casa,
        convalidata=False, 
        gol_fatti=0,
        gol_subiti=0,
        marcatori=''
    )
    aggiunte += 1

print(f"\n🎉 FATTO! {aggiunte} partite caricate con orario esatto.")