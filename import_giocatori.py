import os
import django
from datetime import datetime

# 1. Inizializzazione obbligatoria di Django per gli script esterni
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from squadra_calcio.models import Giocatore

print("Inizio importazione massiccia anagrafiche giocatori...")

def parse_data(data_str):
    if not data_str:
        return None
    try:
        return datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return None

giocatori = [
    {"nome": "Aissaoui Feres", "tel": "3402679465", "data_nascita": "2013-04-18", "identita": "2027-04-18", "visita": "2027-09-07", "categoria": "2013/2014"},
    {"nome": "Belicchi Pietro", "tel": "3358104041", "data_nascita": "2013-02-28", "identita": "2029-02-28", "visita": "2026-12-02", "categoria": "2013/2014"},
    {"nome": "Bellini Gennaro", "tel": "3930080369", "data_nascita": "2013-01-28", "identita": "2029-01-28", "visita": "2026-10-14", "categoria": "2013/2014"},
    {"nome": "Cavvi Sebastian", "tel": "3388807239 / 3398306662", "data_nascita": "2013-12-02", "identita": "2028-12-02", "visita": "2026-12-02", "categoria": "2013/2014"},
    {"nome": "Corradi Mattia", "tel": "3387266458 / 3383395832", "data_nascita": "2013-04-08", "identita": "2030-04-08", "visita": "2027-03-11", "categoria": "2013/2014"},
    {"nome": "De Simoni Alessandro", "tel": "3490587885", "data_nascita": "2013-01-12", "identita": "2029-01-12", "visita": "2027-01-06", "categoria": "2013/2014"},
    {"nome": "Farolini Giovanni", "tel": "3490591362", "data_nascita": "2013-10-31", "identita": "2029-10-31", "visita": "2026-10-14", "categoria": "2013/2014"},
    {"nome": "Ferhane Amine", "tel": "3381675818 / 3510040124", "data_nascita": "2013-10-14", "identita": "2029-12-21", "visita": "2026-09-15", "categoria": "2013/2014"},
    {"nome": "Frati Giorgio Pietro", "tel": "3476990585 / 3358248766", "data_nascita": "2013-12-23", "identita": "2030-12-23", "visita": "2026-11-04", "categoria": "2013/2014"},
    {"nome": "Gangi Climenti Giulio", "tel": "3284180321 / 3889827378", "data_nascita": "2013-11-04", "identita": "2029-11-04", "visita": "2026-11-02", "categoria": "2013/2014"},
    {"nome": "Lusha Ernest", "tel": "3203070805", "data_nascita": "2014-06-20", "identita": "2029-06-20", "visita": "2027-06-17", "categoria": "2013/2014"},
    {"nome": "Mastrapasqua Thomas", "tel": "3397145662", "data_nascita": "2013-06-11", "identita": "2028-06-11", "visita": "2027-06-10", "categoria": "2013/2014"},
    {"nome": "Moussaid Adam", "tel": "3203158891 / 3903158891", "data_nascita": "2014-12-04", "identita": None, "visita": "2026-10-15", "categoria": "2013/2014"},
    {"nome": "Nenna Samuel", "tel": "3342420172 / 3337246722", "data_nascita": "2014-07-15", "identita": "2029-07-15", "visita": "2027-09-08", "categoria": "2013/2014"},
    {"nome": "Ouadoudi Mohamed Adam", "tel": "3278524894", "data_nascita": "2014-02-23", "identita": "2028-02-23", "visita": "2027-02-25", "categoria": "2013/2014"},
    {"nome": "Robuschi Aaron", "tel": "3488206190", "data_nascita": "2013-09-23", "identita": "2031-09-23", "visita": "2027-08-20", "categoria": "2013/2014"},
    {"nome": "Spezia Samuel", "tel": "3343401179 / 3341462162", "data_nascita": "2013-12-01", "identita": "2030-12-01", "visita": "2026-11-18", "categoria": "2013/2014"},
    {"nome": "Xeka Kleisi", "tel": "3891614971 / 3891614971", "data_nascita": "2013-10-30", "identita": "2028-10-30", "visita": "2027-09-01", "categoria": "2013/2014"},
    {"nome": "Accolli Alberto", "tel": "3482430865", "data_nascita": "2011-03-07", "identita": "2027-03-07", "visita": "2027-07-23", "categoria": "2011/2012"},
    {"nome": "Boni Federico", "tel": "3386932175", "data_nascita": "2011-08-11", "identita": "2029-08-11", "visita": "2026-11-18", "categoria": "2011/2012"},
    {"nome": "Borrini Francesco", "tel": "3497416166", "data_nascita": "2012-10-27", "identita": "2029-10-27", "visita": "2027-09-10", "categoria": "2011/2012"},
    {"nome": "Cattabiani Simone", "tel": "3408698183 / 3478561037", "data_nascita": "2012-06-11", "identita": "2028-06-11", "visita": "2026-08-28", "categoria": "2011/2012"},
    {"nome": "Furlotti Nicolò", "tel": "3332857755 / 3493662265", "data_nascita": "2012-10-29", "identita": "2028-10-29", "visita": "2027-09-10", "categoria": "2011/2012"},
    {"nome": "Gorrara Giovanni", "tel": "3479465907 / 3407679551", "data_nascita": "2011-12-31", "identita": "2028-12-31", "visita": "2026-10-21", "categoria": "2011/2012"},
    {"nome": "Groppi Filippo", "tel": "3495370488", "data_nascita": "2011-11-20", "identita": "2028-11-20", "visita": "2026-09-29", "categoria": "2011/2012"},
    {"nome": "Guasti Alessandro", "tel": "3474484454", "data_nascita": "2012-07-24", "identita": "2028-07-24", "visita": "2026-11-18", "categoria": "2011/2012"},
    {"nome": "Latusi Lorenzo", "tel": "3459538640 / 3470585613", "data_nascita": "2012-08-21", "identita": "2031-10-21", "visita": "2027-02-10", "categoria": "2011/2012"},
    {"nome": "Leonardi Mattia", "tel": "3407456719 / 3472288234", "data_nascita": "2011-10-06", "identita": "2029-10-06", "visita": "2027-09-15", "categoria": "2011/2012"},
    {"nome": "Lucchi Gabriele", "tel": "3313716027", "data_nascita": "2011-01-02", "identita": "2031-01-02", "visita": "2026-09-07", "categoria": "2011/2012"},
    {"nome": "Mircea Davide Auras", "tel": "3381991410 / 3381991410", "data_nascita": "2011-04-22", "identita": "2031-04-22", "visita": "2026-10-01", "categoria": "2011/2012"},
    {"nome": "Morelli Christian", "tel": "3494501733 / 3494501733", "data_nascita": "2011-08-17", "identita": "2028-08-17", "visita": "2026-08-31", "categoria": "2011/2012"},
    {"nome": "Motti Davide", "tel": "3498709623 / 3497874250", "data_nascita": "2012-07-10", "identita": "2030-07-10", "visita": "2027-07-22", "categoria": "2011/2012"},
    {"nome": "Panciroli Sebastian", "tel": "3287574273", "data_nascita": "2011-11-23", "identita": "2030-11-23", "visita": "2026-10-16", "categoria": "2011/2012"},
    {"nome": "Rinxhi Davide", "tel": "3200233060 / 3278240405", "data_nascita": "2011-01-12", "identita": "2029-01-12", "visita": "2027-07-10", "categoria": "2011/2012"},
    {"nome": "Selloum Abdarrahman", "tel": "3289145239 / 3203008974", "data_nascita": "2012-10-15", "identita": "2030-10-15", "visita": "2027-09-10", "categoria": "2011/2012"},
    {"nome": "Viappiani Marco", "tel": "3515047340 / 3483813386", "data_nascita": "2011-07-20", "identita": "2031-07-20", "visita": "2027-07-29", "categoria": "2011/2012"},
    {"nome": "Bertinelli Edoardo", "tel": "3474746066 / 3398407918", "data_nascita": "2009-04-18", "identita": "2028-08-18", "visita": "2027-07-28", "categoria": "2009/2010"},
    {"nome": "Caslotti Tiberio", "tel": "3351279541", "data_nascita": "2009-07-25", "identita": "2028-07-25", "visita": "2026-12-30", "categoria": "2009/2010"},
    {"nome": "Ferrari Iacopo", "tel": "3489369883", "data_nascita": "2009-07-24", "identita": "2030-07-20", "visita": "2026-09-15", "categoria": "2009/2010"},
    {"nome": "Hadaoui Yassir", "tel": "3272624324", "data_nascita": "2009-11-22", "identita": "2031-11-22", "visita": "2027-05-05", "categoria": "2009/2010"},
    {"nome": "Jebali Rayan", "tel": "3283770032", "data_nascita": "2010-04-21", "identita": "2028-09-21", "visita": "2026-09-25", "categoria": "2009/2010"},
    {"nome": "Lahnice Rayan", "tel": "3273354111", "data_nascita": "2009-06-24", "identita": "2029-06-24", "visita": "2027-02-10", "categoria": "2009/2010"},
    {"nome": "Legnani Thomas", "tel": "3392877888", "data_nascita": "2010-02-02", "identita": "2028-02-02", "visita": "2027-07-20", "categoria": "2009/2010"},
    {"nome": "Malpeli Lorenzo", "tel": "3287403158", "data_nascita": "2009-02-07", "identita": "2031-02-07", "visita": "2026-10-23", "categoria": "2009/2010"},
    {"nome": "Matichecchia Mattia", "tel": "3475229790", "data_nascita": "2010-04-25", "identita": "2031-04-25", "visita": "2027-02-10", "categoria": "2009/2010"},
    {"nome": "Nasiru Ahmed", "tel": "3881544918", "data_nascita": "2009-09-07", "identita": "2032-07-07", "visita": "2027-05-20", "categoria": "2009/2010"},
    {"nome": "Perrotta Simone", "tel": "3288757748 / 3333675357", "data_nascita": "2009-08-29", "identita": "2031-08-29", "visita": "2026-10-20", "categoria": "2009/2010"}
]

# Inserimento o aggiornamento nel database
for g in giocatori:
    obj, created = Giocatore.objects.update_or_create(
        nome_cognome=g["nome"],
        defaults={
            'categoria': g['categoria'],
            'telefono_genitore': g["tel"],
            'data_nascita': parse_data(g["data_nascita"]),
            'scadenza_carta_identita': parse_data(g["identita"]),
            'scadenza_visita_medica': parse_data(g["visita"])
        }
    )
    if created:
        print(f"✅ NUOVO INSERIMENTO: {g['nome']}")
    else:
        print(f"🔄 AGGIORNATO: {g['nome']}")

print("Importazione anagrafiche completata con successo!")