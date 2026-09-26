import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')  # adatta se il nome settings differisce
django.setup()

from squadra_calcio.models import Giocatore

DATI_DIRIGENTI = """
DAC;NA-04306267;Biondo;Michele;;3421500008;27/04/1950;;BNDMHL50D27C421I;;;;LAB Under 17-18;;;;;;
DAC;NA-04306268;Bonafede;Gianluigi;;3894277524;28/01/2000;;BNFGLG00A28F061Z;;;;LAB;;;;;;
DAC;NA-04304607;Boni;Marco;;3386932175;05/06/1976;;BNOMRC76M05G337D;;;;LAB;;;;;;
DAC;NA-04306269;Borrini;Matteo;;3497416166;04/10/1978;;BRRMTT78R04E463I;;;;LAB Under 15-16;;;;;;
DAC;NA-04306271;Cattabiani;Matteo;;3408698183;02/03/1970;;CTTMTT70C02G337N;;;;LAB Under 15-16;;;;;;
DAC;NA-04306484;Cavvi;Cristian;;3388807239;18/01/1978;;CVVCST78A18G337S;;;;LAB Under 13-14;;;;;;
DAC;NA-04306485;Lama;Vincenzo;;3926163542;19/09/1964;;LMAVCN64P19G337D;;;;LAB Under 17-18;;;;;;
DAC;NA-04306486;Laudadio;Vincenzo;;3404041721;27/06/1971;;LDDVCN71H27L425M;;;;LAB Under 15-16;;;;;;
DAC;NA-04306487;Malpeli;Andrea;;3287403158;27/02/1973;;MLPNDR73B27G337L;;;;LAB Under 17-18;;;;;;
DAC;NA-04306488;Mastrapasqua;Andrea;;3397445662;15/11/1980;;MSTNDR80S15L885B;;;;LAB Under 13-14;;;;;;
DAC;NA-04306489;Matichecchia;Ciro Francesco;;3475229790;10/03/1979;;MTCCFR79C10F205A;;;;LAB;;;;;;
DAC;NA-04306490;Spezia;Marco;;3343401179;12/01/1980;;SPZMRC80A12G337B;;;;LAB Under 13-14;;;;;;
DAC;NA-04306491;Toscani;Andrea;;3343920424;08/08/2006;;TSCNDR06M08G337V;;;;LAB Under 13-14;;;;;;
DAC;NA-04306492;Votta;Michele;;3894916508;15/05/1981;;VTTMHL81E15E977T;;;;LAB Under 15-16;;;;;;
"""

def normalizza_categoria(cat_raw):
    cat = cat_raw.strip()
    if '17-18' in cat:
        return '2009/2010'
    if '15-16' in cat:
        return '2011/2012'
    if '13-14' in cat:
        return '2013/2014'
    return '2013/2014'  # Default per 'LAB'

conteggio = 0
for riga in DATI_DIRIGENTI.strip().split('\n'):
    campi = [c.strip() for c in riga.split(';')]
    if len(campi) < 14:
        continue
    
    tessera_csi = campi[1]
    cognome = campi[2]
    nome = campi[3]
    nome_cognome = f"{nome} {cognome}".strip()
    telefono = campi[5]
    data_nascita_str = campi[6]
    codice_fiscale = campi[8]
    cat_raw = campi[12]

    data_nascita = None
    if data_nascita_str:
        try:
            data_nascita = datetime.strptime(data_nascita_str, "%d/%m/%Y").date()
        except ValueError:
            pass

    categoria_db = normalizza_categoria(cat_raw)

    obj, created = Giocatore.objects.update_or_create(
        tessera_csi=tessera_csi,
        defaults={
            'nome_cognome': nome_cognome,
            'categoria': categoria_db,
            'telefono_giocatore': telefono,
            'data_nascita': data_nascita,
            'codice_fiscale': codice_fiscale,
            'ruolo': 'Dirigente',
            'attivo': True
        }
    )
    conteggio += 1
    azione = "Creato" if created else "Aggiornato"
    print(f"{azione}: {nome_cognome} ({categoria_db}) - CF: {codice_fiscale}")

print(f"\nOperazione completata: {conteggio} dirigenti processati.")