from django.contrib import admin
from .models import ProfiloAtleta, Attivita, TaskSettings, LogSistema, Scarpa
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.utils import timezone

@admin.register(ProfiloAtleta)
class ProfiloAtletaAdmin(admin.ModelAdmin):
    list_display = ('user', 'strava_status', 'token_expiration', 'peso', 'fc_max', 'importa_attivita_private', 'indice_itra')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    list_filter = ('importa_attivita_private', 'mostra_peso')

    @admin.display(description='Strava', boolean=True)
    def strava_status(self, obj):
        return SocialAccount.objects.filter(user=obj.user, provider='strava').exists()

    @admin.display(description='Stato Token')
    def token_expiration(self, obj):
        token = SocialToken.objects.filter(account__user=obj.user, account__provider='strava').first()
        if token and token.expires_at:
            is_expired = token.expires_at < timezone.now()
            status = "⚠️ SCADUTO" if is_expired else "✅ OK"
            return f"{token.expires_at.strftime('%d/%m')} {status}"
        return "❌ NO TOKEN"

@admin.register(Attivita)
class AttivitaAdmin(admin.ModelAdmin):
    list_display = (
        'data',
        'atleta',
        'nome',
        'tipo_attivita',
        'get_distanza_km',
        'dislivello',
        'get_durata_formatted',
        'passo_medio',
        'fc_media',
        'fc_max_sessione',
        'potenza_media',
        'vo2max_stimato',
        'vam',
    )
    list_display_links = ('nome',)
    list_filter = ('atleta', 'tipo_attivita', 'workout_type', 'data')
    search_fields = ('atleta__user__username', 'nome')
    date_hierarchy = 'data'
    ordering = ('-data',)
    list_per_page = 25
    list_select_related = ('atleta__user',)

    # Raggruppa i campi nella vista di dettaglio per una migliore leggibilità
    fieldsets = (
        ('Dati Principali', {'fields': ('atleta', 'nome', 'data', 'tipo_attivita', 'workout_type')}),
        ('Metriche di Performance', {'fields': ('distanza', 'durata', 'passo_medio', 'dislivello', 'vam_selettiva')}),
        ('Dati Fisiologici', {'fields': ('fc_media', 'fc_max_sessione', 'sforzo_relativo')}),
        ('Metriche Avanzate', {'fields': ('potenza_media', 'vo2max_stimato', 'gap_passo', 'cadenza_media', 'analisi_tecnica_ai'), 'classes': ('collapse',)}),
        ('Dati Strava', {'fields': ('strava_activity_id', 'zone_cardiache', 'dispositivo'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('strava_activity_id', 'analisi_tecnica_ai')

    @admin.display(description='Distanza (km)', ordering='distanza')
    def get_distanza_km(self, obj):
        return round(obj.distanza / 1000, 2) if obj.distanza else 0

    @admin.display(description='Durata', ordering='durata')
    def get_durata_formatted(self, obj):
        if obj.durata:
            hours, remainder = divmod(obj.durata, 3600)
            minutes, _ = divmod(remainder, 60)
            if hours > 0:
                return f'{int(hours)}h {int(minutes):02d}m'
            return f'{int(minutes)}m'
        return '-'

@admin.register(TaskSettings)
class TaskSettingsAdmin(admin.ModelAdmin):
    list_display = ('get_task_id_display', 'active', 'manual_trigger', 'hour', 'minute', 'day_of_week')
    list_editable = ('active', 'manual_trigger', 'hour', 'minute', 'day_of_week')
    help_text = "NOTA: Dopo aver modificato questi valori, è necessario riavviare il container 'scheduler' per applicare le modifiche."

@admin.register(LogSistema)
class LogSistemaAdmin(admin.ModelAdmin):
    list_display = ('data', 'livello', 'azione', 'utente', 'messaggio')
    list_filter = ('livello', 'azione', 'data')
    search_fields = ('messaggio', 'utente__username', 'azione')

@admin.register(Scarpa)
class ScarpaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'atleta', 'brand', 'modello_normalizzato', 'distanza', 'primary', 'retired')
    list_filter = ('brand', 'primary', 'retired')
    search_fields = ('nome', 'atleta__user__username')