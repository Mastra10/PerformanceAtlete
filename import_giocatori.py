import os
import django
import random
from datetime import datetime, timedelta

# Configurazione ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from squadra_calcio.models import Giocatore, Evento, Presenza, Risultato

# Liste per la generazione pseudocasuale
NOMI = ['Alessandro', 'Lorenzo', 'Mattia', 'Gabriele', 'Tommaso', 'Riccardo', 'Edoardo', 'Andrea', 'Diego', 'Matteo', 'Federico', 'Francesco', 'Filippo', 'Christian', 'Simone', 'Pietro', 'Samuele', 'Niccolò', 'Davide', 'Jacopo', 'Thomas', 'Kevin', 'Youssef']
COGNOMI = ['Rossi', 'Ferrari', 'Russo', 'Bianchi', 'Romano', 'Gallo', 'Costa', 'Fontana', 'Conti', 'Esposito', 'Ricci', 'Bruno', 'De Luca', 'Moretti', 'Marino', 'Greco', 'Barbieri', 'Lombardi', 'Giordano', 'Cassani', 'Martini', 'Riva', 'Gatti', 'Vitali']
GENITORI = ['Marco', 'Roberto', 'Giuseppe', 'Stefano', 'Paolo', 'Maria', 'Laura', 'Francesca', 'Anna', 'Elena', 'Silvia', 'Massimo']

def random_date(start_year, end_year):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    return (start + timedelta(days=random.randint(0, (end-start).days))).date()

def random_phone():
    return f"+39 3{random.randint(20, 99)} {random.randint(1000000, 9999999)}"

def genera_demo():
    print("🧹 Pulizia profonda del database in corso...")
    Giocatore.objects.all().delete()
    Evento.objects.all().delete()
    Presenza.objects.all().delete()
    Risultato.objects.all().delete()
    
    categorie = [
        {'nome': '2013/2014', 'anni': (2013, 2014)},
        {'nome': '2011/2012', 'anni': (2011, 2012)},
        {'nome': '2009/2010', 'anni': (2009, 2010)},
    ]
    
    oggi = datetime.now().date()
    
    for cat in categorie:
        print(f"⚙️  Generazione della rosa {cat['nome']}...")
        
        # 1. Creazione Staff
        for i in range(2):
            ruolo_staff = 'Dirigente' if i == 0 else 'Allenatore'
            Giocatore.objects.create(
                nome_cognome=f"{random.choice(NOMI)} {random.choice(COGNOMI)}",
                categoria=cat['nome'],
                ruolo=ruolo_staff,
                telefono_giocatore=random_phone(),
                data_nascita=random_date(1975, 1995)
            )

        # 2. Creazione Giocatori
        giocatori_creati = []
        for _ in range(18):
            # 15% di probabilità che una scadenza sia nel passato (per innescare gli allarmi in App)
            scad_visita = oggi + timedelta(days=random.randint(-20, 300))
            scad_carta = oggi + timedelta(days=random.randint(-100, 1500))
            
            g = Giocatore.objects.create(
                nome_cognome=f"{random.choice(NOMI)} {random.choice(COGNOMI)}",
                categoria=cat['nome'],
                ruolo='Giocatore',
                data_nascita=random_date(cat['anni'][0], cat['anni'][1]),
                telefono_giocatore=random_phone(),
                telefono_genitore=f"{random.choice(GENITORI)}: {random_phone()}",
                tessera_csi=f"AT-04{random.randint(10000, 99999)}",
                scadenza_visita_medica=scad_visita,
                scadenza_carta_identita=scad_carta
            )
            giocatori_creati.append(g)
            
        # 3. Generazione Storico Allenamenti (Presenze)
        for i in range(5):
            data_evento = oggi - timedelta(days=(i+1)*4)
            evento = Evento.objects.create(
                categoria_squadra=cat['nome'],
                tipo='Allenamento',
                data=data_evento
            )
            
            for g in giocatori_creati:
                # Simuliamo un 85% di partecipazione
                is_present = random.random() < 0.85
                situazione = '' if is_present else random.choice(['Assenza Giustificata', 'Assenza Ingiustificata'])
                Presenza.objects.create(
                    giocatore=g,
                    evento=evento,
                    presente=is_present,
                    situazione=situazione,
                    firma_dispositivo='DemoSetup'
                )

        # 4. Generazione Partite e Classifica Marcatori
        for i in range(2):
            Risultato.objects.create(
                categoria=cat['nome'],
                data_partita=oggi - timedelta(days=(i+1)*7),
                avversario=f"Real {random.choice(COGNOMI)} F.C.",
                gol_fatti=random.randint(1, 4),
                gol_subiti=random.randint(0, 3),
                marcatori=f"{giocatori_creati[0].nome_cognome} 1, {giocatori_creati[1].nome_cognome} 1"
            )
            
    print("\n✅ Dati DEMO generati con successo! L'app è pronta per essere venduta.")

if __name__ == '__main__':
    genera_demo()