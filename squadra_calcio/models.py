from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from collections import Counter
from django.db import models
from django.contrib.auth.models import User



class CacheApi(models.Model):
    endpoint = models.CharField(max_length=100)
    categoria = models.CharField(max_length=50)
    payload_json = models.TextField() # Qui salveremo il testo generato da Gemini
    ultima_modifica = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('endpoint', 'categoria')

        

class LogConnessione(models.Model):
    utente = models.CharField(max_length=100)
    categoria = models.CharField(max_length=50, blank=True, null=True)
    endpoint = models.CharField(max_length=255)
    metodo = models.CharField(max_length=10) # GET o POST
    status_code = models.IntegerField() # 200 (OK), 400, 500 (Errori)
    data_ora = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_ora']

    def __str__(self):
        return f"{self.utente} - {self.endpoint} [{self.status_code}]"


class DispositivoToken(models.Model):
    utente = models.CharField(max_length=50) # Es. 'Mastra10' o il nome del mister
    token_fcm = models.TextField(unique=True)
    data_aggiornamento = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Token di {self.utente}"


class PrenotazioneCampo(models.Model):
    data_ora_inizio = models.DateTimeField()
    data_ora_fine = models.DateTimeField()
    categoria_richiedente = models.CharField(max_length=50)
    avversario = models.CharField(max_length=100)
    stato = models.CharField(max_length=20, default='In Attesa') # In Attesa, Approvato, Rifiutato
    richiedente = models.CharField(max_length=50)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.categoria_richiedente} vs {self.avversario} - {self.data_ora_inizio}"

class SegnalazioneScouting(models.Model):
    data_creazione = models.DateTimeField(auto_now_add=True)
    squadra_avversaria = models.CharField(max_length=100)
    categoria_avversaria = models.CharField(max_length=50)
    nome_giocatore = models.CharField(max_length=100)
    note = models.TextField()
    segnalatore = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.nome_giocatore} ({self.squadra_avversaria})"


# Un "profilo" collegato a ogni utente
class ProfiloMister(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profilo')
    # Quando si registra, Flutter manderà qui la categoria scelta (es. '2013/2014')
    categoria_gestita = models.CharField(max_length=50, blank=True, null=True) 

    def __str__(self):
        return f"Profilo di {self.user.username} ({self.categoria_gestita})"

class Categoria(models.TextChoices):
    CAT_09_10 = '2009/2010', 'Allievi (2009/2010)'
    CAT_11_12 = '2011/2012', 'Giovanissimi (2011/2012)'
    CAT_13_14 = '2013/2014', 'Esordienti (2013/2014)'

#class Categoria(models.TextChoices):
#    LAB = 'LAB', 'LAB (Prima Squadra/Generico)'
#    CAT_U17_18 = 'LAB Under 17-18', 'LAB Under 17-18'
#    CAT_U15_16 = 'LAB Under 15-16', 'LAB Under 15-16'
#    CAT_U13_14 = 'LAB Under 13-14', 'LAB Under 13-14'


class Giocatore(models.Model):
    nome_cognome = models.CharField(max_length=150)
    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    
    # Contatti e Burocrazia
    telefono_giocatore = models.CharField(max_length=150, blank=True, null=True)
    telefono_genitore = models.CharField(max_length=150, blank=True, null=True, help_text="Specifica anche il nome se necessario")
    scadenza_certificato = models.DateField(blank=True, null=True, verbose_name="Scadenza Certificato Medico")
    modulo_golee_compilato = models.BooleanField(default=False, verbose_name="Modulo Golee")
    scadenza_visita_medica = models.DateField(null=True, blank=True)
    scadenza_carta_identita = models.DateField(null=True, blank=True)
    tessera_csi = models.CharField(max_length=50, null=True, blank=True)
    tessera_figc = models.CharField(max_length=50, null=True, blank=True)

    # NUOVI CAMPI:
    data_nascita = models.DateField(null=True, blank=True)
    RUOLI_SCELTE = [
        ('Giocatore', 'Giocatore'),
        ('Allenatore', 'Allenatore'),
        ('Dirigente', 'Dirigente'),
    ]
    ruolo = models.CharField(max_length=50, choices=RUOLI_SCELTE, default='Giocatore')


    attivo = models.BooleanField(default=True)
    note_mediche = models.TextField(blank=True, null=True, help_text="Allergie, infortuni pregressi, ecc.")

    class Meta:
        verbose_name_plural = "Giocatori"
        ordering = ['categoria', 'nome_cognome']

    def __str__(self):
        return f"{self.nome_cognome} ({self.categoria})"

    # --- INIZIO SEZIONE STATISTICHE (Calcolate al volo, senza pesare sul DB) ---
    @property
    def certificato_scaduto(self):
        if not self.scadenza_certificato:
            return True
        return self.scadenza_certificato < timezone.now().date()

    @property
    def stat_presenze_allenamenti(self):
        """Ritorna % presenze agli allenamenti"""
        totali = self.presenze.filter(evento__tipo='Allenamento').count()
        if totali == 0: return 0
        presente = self.presenze.filter(evento__tipo='Allenamento', presente=True).count()
        return round((presente / totali) * 100, 1)

    @property
    def stat_partite_giocate(self):
        """Numero totale di partite a cui ha partecipato"""
        return self.presenze.filter(evento__tipo='Partita', presente=True).count()

    @property
    def giorno_peggiore(self):
        """Calcola in quale giorno della settimana il giocatore manca di più agli allenamenti"""
        assenze = self.presenze.filter(evento__tipo='Allenamento', presente=False)
        if not assenze.exists():
            return "Sempre presente"
        
        # 0=Lunedì, 1=Martedì, ecc.
        giorni_mancati = [assenza.evento.data.weekday() for assenza in assenze]
        giorno_piu_frequente = Counter(giorni_mancati).most_common(1)[0][0]
        
        nomi_giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        return nomi_giorni[giorno_piu_frequente]


class Evento(models.Model):
    TIPO_CHOICES = [
        ('Allenamento', 'Allenamento'),
        ('Partita', 'Partita di Campionato'),
        ('Amichevole', 'Partita Amichevole')
    ]
    
    categoria_squadra = models.CharField(max_length=20, choices=Categoria.choices, verbose_name="Squadra Interessata")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='Allenamento')
    data = models.DateTimeField()
    luogo = models.CharField(max_length=150, blank=True, null=True, default="Campo Sportivo")
    
    # Campi specifici per le PARTITE (Calendario)
    avversario = models.CharField(max_length=150, blank=True, null=True)
    in_casa = models.BooleanField(default=True)
    gol_nostri = models.IntegerField(blank=True, null=True)
    gol_avversari = models.IntegerField(blank=True, null=True)
    
    note_evento = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Eventi (Calendario)"
        ordering = ['-data']

    def __str__(self):
        if self.tipo in ['Partita', 'Amichevole']:
            vs = f"vs {self.avversario}" if self.in_casa else f"@ {self.avversario}"
            return f"{self.tipo} {self.categoria_squadra} {vs} - {self.data.strftime('%d/%m')}"
        return f"Allenamento {self.categoria_squadra} - {self.data.strftime('%d/%m')}"


class Presenza(models.Model):
    giocatore = models.ForeignKey(Giocatore, on_delete=models.CASCADE, related_name='presenze')
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='presenze_registrate')
    
    presente = models.BooleanField(default=False)
    situazione = models.CharField(max_length=100, blank=True, null=True, help_text="Es. Infortunato, Malato, Assente ingiustificato")
    
    # Statistiche specifiche per la singola presenza
    minuti_giocati = models.IntegerField(blank=True, null=True, help_text="Compilare se è una Partita")
    
    # Audit: chi dei 5 dirigenti ha messo la spunta?
    # registrato_da = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    # Sostituiamo (o affianchiamo) registrato_da con questo:
    firma_dispositivo = models.CharField(max_length=100, blank=True, null=True, help_text="Nome inserito nell'app")
    data_registrazione = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Presenze"
        unique_together = ('giocatore', 'evento') 

    def __str__(self):
        stato = 'Presente' if self.presente else 'Assente'
        return f"{self.giocatore.nome_cognome} - {self.evento} - {stato}"


# --- MODELLI PER LA CLASSIFICA CSI ---
class Campionato(models.Model):
    nome = models.CharField(max_length=100, help_text="Es. CSI Parma Primavera")
    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    stagione = models.CharField(max_length=11, default="2026/2027")

    class Meta:
        verbose_name_plural = "Campionati"

    def __str__(self):
        return f"{self.nome} - {self.categoria}"

class SquadraClassifica(models.Model):
    campionato = models.ForeignKey(Campionato, on_delete=models.CASCADE, related_name='squadre')
    nome_squadra = models.CharField(max_length=150)
    is_nostra_squadra = models.BooleanField(default=False)
    
    punti = models.IntegerField(default=0)
    partite_giocate = models.IntegerField(default=0)
    vittorie = models.IntegerField(default=0)
    pareggi = models.IntegerField(default=0)
    sconfitte = models.IntegerField(default=0)
    gol_fatti = models.IntegerField(default=0)
    gol_subiti = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = "Voci Classifica"
        ordering = ['-punti', '-gol_fatti']

    def __str__(self):
        return f"{self.nome_squadra} - {self.punti} pt"
    
class LogModifica(models.Model):
    data_ora = models.DateTimeField(auto_now_add=True)
    utente = models.CharField(max_length=100)
    azione = models.CharField(max_length=255)

    class Meta:
        ordering = ['-data_ora']

class Risultato(models.Model):
    categoria = models.CharField(max_length=50)
    data_partita = models.DateField()
    orario = models.TimeField(null=True, blank=True)
    avversario = models.CharField(max_length=150)
    gol_fatti = models.IntegerField(default=0)
    gol_subiti = models.IntegerField(default=0)
    marcatori = models.TextField(blank=True, null=True)
    
    # --- NUOVI CAMPI PER IL CALENDARIO ---
    giornata = models.IntegerField(null=True, blank=True) # Es: 1 per "1ª Giornata"
    in_casa = models.BooleanField(default=True)           # True se il Fraore gioca in casa
    convalidata = models.BooleanField(default=True)       # False = Da Giocare, True = Giocata (fa media)

    def __str__(self):
        stato = "Convalidata" if self.convalidata else "Da Giocare"
        return f"{self.data_partita} | Fraore vs {self.avversario} [{stato}]"

class AllarmeAck(models.Model):
    giocatore_id = models.IntegerField()
    chiave_allarme = models.CharField(max_length=100) # Es: "visita_2026", "compleanno_2026", "assenza_settembre"
    data_ack = models.DateTimeField(auto_now_add=True)