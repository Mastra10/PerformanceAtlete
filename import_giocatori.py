from squadra_calcio.models import Giocatore

print("Inizio creazione anagrafiche giocatori...")

# Lista esatta ricavata dal tuo foglio cartaceo "81354_2.jpg"
giocatori = [
    {"nome": "Aissaoui Feres", "tel": ""},
    {"nome": "Belicchi Pietro", "tel": ""},
    {"nome": "Cavvi Sebastian", "tel": ""},
    {"nome": "Corradi Mattia", "tel": ""},
    {"nome": "De Simoni Alessandro", "tel": ""},
    {"nome": "Farolini Giovanni", "tel": ""},
    {"nome": "Gangi Chimenti Giulio", "tel": ""},
    {"nome": "Mastrapasqua Thomas", "tel": ""},
    {"nome": "Robuschi Aaron", "tel": ""},
    {"nome": "Spezia Samuel", "tel": ""},
    {"nome": "Ferhane Mohamed Amine", "tel": ""},
    {"nome": "Bellini Gennaro", "tel": ""},
    {"nome": "Giorgio Frati", "tel": "347 6990585 / 335 8248766"},
    {"nome": "Lusha Ernest", "tel": "351 3151341"},
    {"nome": "Nenna Samuel", "tel": "334 2420172"},
    {"nome": "Ouadoudi Mohamed Adam", "tel": ""},
    {"nome": "Adam Mussaid", "tel": ""},
    {"nome": "D'Ambrosio Gabriele", "tel": ""},
    {"nome": "Viletta Gianluca", "tel": ""},
    {"nome": "Adam ben Ahmam", "tel": "320 2270671"},
    {"nome": "Kleisi Xeka", "tel": "380 7668759 / 371 6838713"},
    {"nome": "Abdalle Fahd", "tel": ""},
    {"nome": "Iazzi Gabriel", "tel": ""},
    {"nome": "Spelorzi Manuel", "tel": ""}
]

# Li inseriamo o li aggiorniamo nel database
for g in giocatori:
    obj, created = Giocatore.objects.update_or_create(
        nome_cognome=g["nome"],
        defaults={
            'categoria': '2013/2014',
            'telefono_genitore': g["tel"]
        }
    )
    if created:
        print(f"✅ NUOVO INSERIMENTO: {g['nome']}")
    else:
        print(f"🔄 AGGIORNATO: {g['nome']}")

print("Importazione anagrafiche completata con successo!")