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
    dashboard_pubblica = models.BooleanField(default=False, verbose_name="Rendi dashboard pubblica")
    eta = models.IntegerField(default=30)
    fc_riposo = models.IntegerField(help_text="Battiti a riposo", null=True, blank=True)
    immagine_profilo = models.URLField(max_length=500, blank=True, null=True)
    fc_max = models.IntegerField(help_text="Battiti massimi", default=190)
    fc_massima_teorica = models.IntegerField(default=190)
    # Risultato dell'analisi AI
    vo2max_stima_statistica = models.FloatField(blank=True, null=True, verbose_name="VO2max Stima (Trail+Strada)")
    vo2max_strada = models.FloatField(blank=True, null=True, verbose_name="VO2max Solo Strada")
    ultima_analisi_ai = models.TextField(blank=True, null=True)
    data_ultima_analisi = models.DateTimeField(auto_now=True)
    
    # Indici ITRA e UTMB
    indice_itra = models.IntegerField(default=0, verbose_name="ITRA Index")
    indice_utmb = models.IntegerField(default=0, verbose_name="UTMB Index")
    data_aggiornamento_indici = models.DateTimeField(null=True, blank=True)

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