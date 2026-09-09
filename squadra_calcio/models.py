from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from collections import Counter

class Categoria(models.TextChoices):
    CAT_09_10 = '2009/2010', 'Allievi (2009/2010)'
    CAT_11_12 = '2011/2012', 'Giovanissimi (2011/2012)'
    CAT_13_14 = '2013/2014', 'Esordienti (2013/2014)'

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