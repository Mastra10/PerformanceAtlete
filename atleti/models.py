from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class ProfiloAtleta(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    strava_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    
    # Dati biometrici fondamentali per Gemini
    peso = models.FloatField(help_text="In kg", null=True, blank=True)
    mostra_peso = models.BooleanField(default=True, verbose_name="Mostra peso in classifica")
    peso_manuale = models.BooleanField(default=False, verbose_name="Peso impostato manualmente")
    dashboard_pubblica = models.BooleanField(default=False, verbose_name="Rendi dashboard pubblica")
    eta = models.IntegerField(default=30)
    fc_riposo = models.IntegerField(help_text="Battiti a riposo", null=True, blank=True)
    immagine_profilo = models.URLField(max_length=500, blank=True, null=True)
    fc_max = models.IntegerField(help_text="Battiti massimi", default=190)
    fc_massima_teorica = models.IntegerField(default=190)
    fc_max_manuale = models.BooleanField(default=False, verbose_name="FC Max impostata manualmente")
    data_fc_max = models.DateField(null=True, blank=True, verbose_name="Data rilevamento FC Max")
    # Risultato dell'analisi AI
    vo2max_stima_statistica = models.FloatField(blank=True, null=True, verbose_name="VO2max Stima (Trail+Strada)")
    vo2max_strada = models.FloatField(blank=True, null=True, verbose_name="VO2max Solo Strada")
    ultima_analisi_ai = models.TextField(blank=True, null=True)
    data_ultima_analisi = models.DateTimeField(auto_now=True)
    
    # Indici ITRA e UTMB
    indice_itra = models.IntegerField(default=0, verbose_name="ITRA Index")
    indice_utmb = models.IntegerField(default=0, verbose_name="UTMB Index")
    data_aggiornamento_indici = models.DateTimeField(null=True, blank=True)
    
    data_ultima_sincronizzazione = models.DateTimeField(null=True, blank=True, verbose_name="Ultima Sincronizzazione Strava")
    data_ultimo_ricalcolo_statistiche = models.DateTimeField(null=True, blank=True, verbose_name="Ultimo Ricalcolo Statistiche")

    def __str__(self):
        return f"Profilo di {self.user.username}"

class Attivita(models.Model):
    atleta = models.ForeignKey(ProfiloAtleta, on_delete=models.CASCADE, related_name='sessioni')
    strava_activity_id = models.BigIntegerField(unique=True)
    data = models.DateTimeField()
    distanza = models.FloatField(help_text="In metri")
    durata = models.IntegerField(help_text="In secondi")
    passo_medio = models.CharField(max_length=10)
    fc_media = models.IntegerField(null=True, blank=True)
    fc_max_sessione = models.IntegerField(null=True, blank=True)
    dislivello = models.FloatField(default=0.0)
    cadenza_media = models.FloatField(null=True, blank=True)
    sforzo_relativo = models.IntegerField(null=True, blank=True) # "Relative Effort" di Strava
    potenza_media = models.FloatField(null=True, blank=True) # Utile se usano sensori
    gap_passo = models.FloatField(null=True, blank=True, help_text="Passo GAP in m/s")
    # Campo per le zone cardiache (salvato come testo JSON per semplicità)
    zone_cardiache = models.JSONField(null=True, blank=True)
    vam_selettiva = models.FloatField(null=True, blank=True, help_text="VAM calcolata su pendenze > 7%")

    tipo_attivita = models.CharField(max_length=20, default='Run') # 'Run' o 'TrailRun'
    nome = models.CharField(max_length=200, null=True, blank=True)
    workout_type = models.IntegerField(null=True, blank=True, help_text="1=Gara, 2=Lungo, 3=Lavoro")
    
    # Campi compilati da Gemini
    vo2max_stimato = models.FloatField(null=True, blank=True)
    analisi_tecnica_ai = models.TextField(blank=True, null=True)
    battito_riposo = models.IntegerField(null=True, blank=True)
    

    class Meta:
        verbose_name_plural = "Attività"

    def __str__(self):
        return f"Corsa {self.data.date()} - {self.atleta.user.username}"
    
    @property
    def vam(self):
        """Calcola la Velocità Ascensionale Media (m/h) solo per TrailRun"""
        if self.vam_selettiva:
            return int(self.vam_selettiva)
        if self.tipo_attivita == 'TrailRun' and self.durata > 0 and self.dislivello > 0:
            return int((self.dislivello / self.durata) * 3600)
        return 0
    
    @property
    def vo2max_assoluto(self):
        """Calcola VO2max Assoluto in L/min"""
        peso = self.atleta.peso if (self.atleta.peso and self.atleta.peso > 0) else 70.0
        if self.vo2max_stimato:
            return round((self.vo2max_stimato * peso) / 1000, 2)
        return None

    @property
    def kcal_stimate(self):
        """Stima Kcal basata su VO2 dell'attività"""
        peso = self.atleta.peso if (self.atleta.peso and self.atleta.peso > 0) else 70.0
        if self.durata <= 0: return None
        
        # Ricostruzione VO2 Attività (approssimata per display)
        distanza_metri = self.distanza
        durata_secondi = self.durata
        d_plus = self.dislivello
        
        if self.tipo_attivita == 'TrailRun':
             # Se è una Gara (workout_type=1), usiamo la formula potenziata
             if self.workout_type == 1:
                 distanza_equivalente = distanza_metri + (5 * d_plus)
                 velocita_eq = distanza_equivalente / (durata_secondi / 60)
                 vo2_attivita = (0.2 * velocita_eq * 1.05) + 3.5
             else:
                 distanza_equivalente = distanza_metri + (5 * d_plus)
                 velocita_eq = distanza_equivalente / (durata_secondi / 60)
                 vo2_attivita = (0.2 * velocita_eq * 1.05) + 3.5
        else:
             velocita_m_min = distanza_metri / (durata_secondi / 60)
             pendenza = d_plus / distanza_metri if distanza_metri > 0 else 0
             vo2_attivita = (0.2 * velocita_m_min) + (0.9 * velocita_m_min * pendenza) + 3.5
             
        return int(((vo2_attivita - 3.5) * peso * (durata_secondi / 60) * 5) / 1000)

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        ProfiloAtleta.objects.get_or_create(user=instance)


@property
def distanza_km(self):
    if self.distanza:
        return round(self.distanza / 1000, 2)
    return 0        

class TaskSettings(models.Model):
    TASK_CHOICES = [
        ('ricalcolo_vam_notturno', 'Ricalcolo VAM'),
        ('ricalcolo_stats_notturno', 'Ricalcolo Statistiche'),
        ('scrape_itra_utmb_settimanale', 'Scraping ITRA/UTMB'),
        ('pulizia_log_settimanale', 'Pulizia Log'),
        ('sync_strava_periodico', 'Sync Strava Automatico'),
    ]
    task_id = models.CharField(max_length=50, choices=TASK_CHOICES, unique=True, verbose_name="Task")
    active = models.BooleanField(default=True, verbose_name="Attivo")
    hour = models.CharField(max_length=10, default="*", verbose_name="Ora (0-23 o *)")
    minute = models.CharField(max_length=10, default="0", verbose_name="Minuto (0-59 o *)")
    day_of_week = models.CharField(max_length=20, default="*", verbose_name="Giorno (mon,tue... o *)")
    manual_trigger = models.BooleanField(default=False, verbose_name="Esecuzione Manuale Richiesta")

    class Meta:
        verbose_name = "Configurazione Scheduler"
        verbose_name_plural = "Configurazione Scheduler"

    def __str__(self):
        return self.get_task_id_display()

class LogSistema(models.Model):
    """Log applicativi salvati su DB per debug e verifica"""
    LIVELLI = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Errore'),
    ]
    data = models.DateTimeField(auto_now_add=True)
    livello = models.CharField(max_length=10, choices=LIVELLI, default='INFO')
    azione = models.CharField(max_length=50) # Es. "Sync Strava", "Calcolo VAM"
    messaggio = models.TextField()
    utente = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Log Sistema"
        verbose_name_plural = "Log Sistema"
        ordering = ['-data']

    def __str__(self):
        return f"{self.data.strftime('%d/%m %H:%M')} - {self.azione}"