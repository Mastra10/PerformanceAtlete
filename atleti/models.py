from django.db import models
from django.contrib.auth.models import User, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from zoneinfo import ZoneInfo
from django.contrib.auth.signals import user_logged_in

class ProfiloAtleta(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    strava_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    
    # Dati biometrici fondamentali per Gemini
    peso = models.FloatField(help_text="In kg", null=True, blank=True)
    mostra_peso = models.BooleanField(default=True, verbose_name="Mostra peso in classifica")
    peso_manuale = models.BooleanField(default=False, verbose_name="Peso impostato manualmente")
    dashboard_pubblica = models.BooleanField(default=False, verbose_name="Rendi dashboard pubblica")
    importa_attivita_private = models.BooleanField(default=False, verbose_name="Importa attività private da Strava")
    condividi_metriche = models.BooleanField(default=True, verbose_name="Condividi VO2max e Indici nel riepilogo")
    escludi_statistiche_coach = models.BooleanField(default=False, verbose_name="Escludimi dalle statistiche Coach")
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
    # Preferenza per nascondere l'avviso temporaneo nella home (persistente per utente)
    hide_home_notice = models.BooleanField(default=False, verbose_name="Nascondi avviso home")

    class Meta:
        permissions = [
            ("access_riepilogo", "Può accedere al Riepilogo Atleti"),
            ("access_coach_dashboard", "Può accedere alla Dashboard Coach"),
            ("access_confronto", "Può accedere al Confronto"),
            ("access_attrezzatura", "Può accedere all'Attrezzatura"),
            ("access_gare", "Può accedere alle Gare"),
            ("access_grafici", "Può accedere ai Grafici"),
        ]

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
    piazzamento = models.IntegerField(null=True, blank=True, verbose_name="Posizione in classifica")
    dispositivo = models.CharField(max_length=100, null=True, blank=True, verbose_name="Dispositivo GPS")
    

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

    @property
    def distanza_km(self):
        if self.distanza:
            return round(self.distanza / 1000, 2)
        return 0
        
    @property
    def durata_formattata(self):
        hours, remainder = divmod(self.durata, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f'{int(hours)}h {int(minutes):02d}m'
        return f'{int(minutes)}m'

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        ProfiloAtleta.objects.get_or_create(user=instance)
        
        # Assegnazione automatica permessi ai nuovi utenti
        try:
            content_type = ContentType.objects.get_for_model(ProfiloAtleta)
            perms = Permission.objects.filter(
                content_type=content_type,
                codename__in=[
                    'access_riepilogo', 'access_coach_dashboard', 
                    'access_confronto', 'access_attrezzatura', 
                    'access_gare', 'access_grafici'
                ]
            )
            instance.user_permissions.add(*perms)
        except Exception as e:
            print(f"Errore assegnazione permessi default: {e}")

@receiver(user_logged_in)
def ensure_permissions_on_login(sender, user, request, **kwargs):
    """
    Assegna i permessi di default a ogni login.
    Garantisce che anche gli utenti già registrati ricevano i nuovi menu.
    """
    try:
        ProfiloAtleta.objects.get_or_create(user=user)
        content_type = ContentType.objects.get_for_model(ProfiloAtleta)
        perms = Permission.objects.filter(
            content_type=content_type,
            codename__in=[
                'access_riepilogo', 'access_coach_dashboard', 
                'access_confronto', 'access_attrezzatura', 
                'access_gare', 'access_grafici'
            ]
        )
        user.user_permissions.add(*perms)
    except Exception as e:
        print(f"Errore assegnazione permessi login: {e}")

class TaskSettings(models.Model):
    TASK_CHOICES = [
        ('ricalcolo_vam_notturno', 'Ricalcolo VAM'),
        ('ricalcolo_stats_notturno', 'Ricalcolo Statistiche'),
        ('scrape_itra_utmb_settimanale', 'Scraping ITRA/UTMB'),
        ('pulizia_log_settimanale', 'Pulizia Log'),
        ('sync_strava_periodico', 'Sync Strava Automatico'),
        ('repair_strava_settimanale', 'Riparazione Strava (Self-Healing)'),
        ('aggiorna_podio_ai_4h', 'Aggiornamento Podio AI'),
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

class Scarpa(models.Model):
    atleta = models.ForeignKey(ProfiloAtleta, on_delete=models.CASCADE, related_name='scarpe')
    strava_id = models.CharField(max_length=50, unique=True)
    nome = models.CharField(max_length=200)
    distanza = models.FloatField(default=0.0) # in metri
    primary = models.BooleanField(default=False)
    brand = models.CharField(max_length=100, null=True, blank=True)
    modello_normalizzato = models.CharField(max_length=200, null=True, blank=True)
    retired = models.BooleanField(default=False, verbose_name="Dismessa")

    class Meta:
        verbose_name_plural = "Scarpe"
        ordering = ['-distanza']

    def __str__(self):
        return f"{self.nome} ({self.atleta.user.username})"
        
    @property
    def distanza_km(self):
        return round(self.distanza / 1000, 1)

class Allenamento(models.Model):
    TIPO_CHOICES = [('Trail', 'Trail Running'), ('Strada', 'Corsa su Strada')]
    VISIBILITA_CHOICES = [('Pubblico', 'Pubblico (Tutti)'), ('Privato', 'Privato (Solo Invitati)')]

    creatore = models.ForeignKey(User, on_delete=models.CASCADE, related_name='allenamenti_creati')
    titolo = models.CharField(max_length=200)
    descrizione = models.TextField(blank=True)
    data_orario = models.DateTimeField()
    distanza_km = models.FloatField()
    dislivello = models.IntegerField(default=0, help_text="Dislivello positivo in metri")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='Strada')
    tempo_stimato = models.DurationField(help_text="Tempo previsto (HH:MM:SS)")
    file_gpx = models.FileField(upload_to='gpx_track/', null=True, blank=True)
    visibilita = models.CharField(max_length=10, choices=VISIBILITA_CHOICES, default='Pubblico')
    invitati = models.ManyToManyField(User, related_name='inviti_allenamento', blank=True)
    data_creazione = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Allenamenti"
        ordering = ['-data_orario']

    def __str__(self):
        return f"{self.titolo} ({self.data_orario.date()})"

    def save(self, *args, **kwargs):
        if self.data_orario and timezone.is_naive(self.data_orario):
            self.data_orario = timezone.make_aware(self.data_orario, ZoneInfo("Europe/Rome"))
        super().save(*args, **kwargs)

class Partecipazione(models.Model):
    STATO_CHOICES = [
        ('Richiesta', 'In Attesa'),
        ('Approvata', 'Approvata'),
        ('Rifiutata', 'Rifiutata')
    ]

    allenamento = models.ForeignKey(Allenamento, on_delete=models.CASCADE, related_name='partecipanti')
    atleta = models.ForeignKey(User, on_delete=models.CASCADE)
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default='Richiesta')
    motivo_rifiuto = models.TextField(blank=True, null=True)
    
    # Analisi Rischio
    is_at_risk = models.BooleanField(default=False)
    risk_reason = models.CharField(max_length=255, blank=True, null=True)
    data_richiesta = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('allenamento', 'atleta')

    def check_risk(self):
        """Confronta il passo richiesto con il VO2max dell'atleta"""
        profilo = getattr(self.atleta, 'profiloatleta', None)
        if not profilo or not profilo.vo2max_stima_statistica:
            self.is_at_risk = True
            self.risk_reason = "Dati VO2max atleta mancanti."
            return

        # Calcolo VO2 richiesto per l'allenamento
        # Convertiamo tutto in minuti
        durata_min = self.allenamento.tempo_stimato.total_seconds() / 60
        if durata_min <= 0: return
        
        # Distanza equivalente (Sforzo): 100m D+ = 1km piano (regola base trail)
        dist_eq_km = self.allenamento.distanza_km + (self.allenamento.dislivello / 100)
        velocita_req_m_min = (dist_eq_km * 1000) / durata_min
        
        # Formula inversa approssimata ACSM: VO2 = (0.2 * v) + 3.5
        # Aggiungiamo un buffer del 10% per il terreno se Trail
        factor = 1.10 if self.allenamento.tipo == 'Trail' else 1.0
        vo2_req = ((0.2 * velocita_req_m_min) + 3.5) * factor
        
        # Soglia di rischio: Se il VO2 richiesto supera l'80% del VO2max dell'atleta
        soglia_sostenibile = profilo.vo2max_stima_statistica * 0.80
        
        if vo2_req > soglia_sostenibile:
            self.is_at_risk = True
            self.risk_reason = f"Intensità stimata troppo alta ({int(vo2_req)} ml/kg/min richiesti vs {int(soglia_sostenibile)} sostenibili)."
        else:
            self.is_at_risk = False
            self.risk_reason = ""

class CommentoAllenamento(models.Model):
    allenamento = models.ForeignKey(Allenamento, on_delete=models.CASCADE, related_name='commenti')
    autore = models.ForeignKey(User, on_delete=models.CASCADE)
    testo = models.TextField()
    data = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Commento di {self.autore} su {self.allenamento}"

class Notifica(models.Model):
    utente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifiche')
    messaggio = models.CharField(max_length=255)
    link = models.CharField(max_length=200, blank=True, null=True)
    letta = models.BooleanField(default=False)
    data_creazione = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=20, default='info') # info, warning, success

    class Meta:
        ordering = ['-data_creazione']

    def __str__(self):
        return f"Notifica per {self.utente}: {self.messaggio}"