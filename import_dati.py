from squadra_calcio.models import Giocatore, Evento, Presenza

print("Inizio pulizia e importazione COMPLETA a 6 date...")

# 1. CANCELLAZIONE VECCHI ALLENAMENTI
vecchi_allenamenti = Evento.objects.filter(tipo='allenamento')
conteggio = vecchi_allenamenti.count()
vecchi_allenamenti.delete()
print(f"🗑️ Cancellati {conteggio} vecchi allenamenti dal database.")

# 2. CREAZIONE DELLE 6 NUOVE DATE
date_allenamenti = [
    "2026-08-24", # 1. Lunedì 24 agosto
    "2026-08-27", # 2. Giovedì 27 agosto
    "2026-09-01", # 3. Martedì 1 settembre (prima della riga)
    "2026-09-03", # 4. Giovedì 3 settembre (dopo la riga)
    "2026-09-04", # 5. Venerdì 4 settembre (Situazione prima parte)
    "2026-09-08", # 6. Martedì 8 settembre (Situazione seconda parte)
]

eventi = []
for d in date_allenamenti:
    evento, _ = Evento.objects.get_or_create(
        data=d,
        tipo='allenamento',
        defaults={'note_evento': 'Allenamento ore 18-19:30'}
    )
    eventi.append(evento)
print("✅ Create le 6 nuove date degli allenamenti.")

# 3. MAPPA DATI (6 VALORI PER OGNI GIOCATORE)
# I "-" e i "?" verranno convertiti automaticamente in "Assenza Ingiustificata"
dati_presenze = {
    "Aissaoui Feres": ["A G", "A G", "A G", "A G", "A G", "-"],
    "Belicchi Pietro": ["V", "V", "A G", "A G", "A G", "V"],
    "Cavvi Sebastian": ["V", "V", "V", "V", "V", "V"],
    "Corradi Mattia": ["V", "V", "A G", "V", "V", "V"],
    "De Simoni Alessandro": ["V", "V", "A G", "V", "V", "V"],
    "Farolini Giovanni": ["A G", "A G", "V", "V", "V", "V"],
    "Gangi Chimenti Giulio": ["A G", "A G", "V", "V", "V", "V"],
    "Mastrapasqua Thomas": ["V", "-", "V", "V", "V", "V"],
    "Robuschi Aaron": ["A G", "-", "V", "V", "V", "V"],
    "Spezia Samuel": ["V", "A G", "V", "V", "V", "V"],
    "Ferhane Mohamed Amine": ["V", "V", "V", "V", "V", "V"],
    "Bellini Gennaro": ["V", "V", "V", "A NON G", "V", "V"],
    "Giorgio Frati": ["V", "V", "V", "V", "-", "A G"],
    "Lusha Ernest": ["-", "V", "V", "V", "V", "V"],
    "Nenna Samuel": ["A", "A", "V", "V", "V", "A G"],
    "Ouadoudi Mohamed Adam": ["A NON G", "A NON G", "A NON G", "A NON G", "V", "V"],
    "Adam Mussaid": ["?", "?", "?", "?", "?", "-"],
    "D'Ambrosio Gabriele": ["?", "?", "?", "?", "?", "-"],
    "Viletta Gianluca": ["?", "?", "?", "?", "?", "-"],
    "Adam ben Ahmam": ["-", "V", "A NON G", "A NON G", "-", "-"],
    "Kleisi Xeka": ["-", "-", "-", "V", "V", "V"],
}

# Funzione logica per interpretare il foglio
def analizza_stato(valore):
    if not valore or valore.strip() in ["-", "?", ""]: 
        return {"presente": False, "situazione": "Assenza Ingiustificata"}
    
    v = valore.strip().upper()
    if "V" in v: 
        return {"presente": True, "situazione": ""}
    if "NON" in v: 
        return {"presente": False, "situazione": "Assenza Ingiustificata"}
    if "A G" in v or v == "A": 
        return {"presente": False, "situazione": "Assenza Giustificata"}
    
    # Qualsiasi altra cosa non riconosciuta finisce in ingiustificata
    return {"presente": False, "situazione": "Assenza Ingiustificata"}

# 4. INSERIMENTO DELLE 6 PRESENZE PER OGNI GIOCATORE
for nome, presenze_lista in dati_presenze.items():
    giocatore = Giocatore.objects.filter(nome_cognome__icontains=nome).first()
    
    if not giocatore:
        print(f"⚠️ Giocatore saltato (non trovato nel DB): {nome}")
        continue

    for i, stato_str in enumerate(presenze_lista):
        stato = analizza_stato(stato_str)
        Presenza.objects.create(
            giocatore=giocatore,
            evento=eventi[i],
            presente=stato['presente'],
            situazione=stato['situazione'],
            firma_dispositivo='Import_Massivo'
        )

print("⚽ Boom! 6 Date inserite e presenze calcolate perfettamente.")