from django.contrib import admin
from .models import ProfiloAtleta, Attivita, TaskSettings

@admin.register(ProfiloAtleta)
class ProfiloAtletaAdmin(admin.ModelAdmin):
    list_display = ('user', 'peso', 'fc_max', 'indice_itra', 'indice_utmb')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')

@admin.register(Attivita)
class AttivitaAdmin(admin.ModelAdmin):
    list_display = ('data', 'atleta', 'tipo_attivita', 'distanza', 'dislivello')
    list_filter = ('tipo_attivita', 'data')
    search_fields = ('atleta__user__username',)

@admin.register(TaskSettings)
class TaskSettingsAdmin(admin.ModelAdmin):
    list_display = ('get_task_id_display', 'active', 'hour', 'minute', 'day_of_week')
    list_editable = ('active', 'hour', 'minute', 'day_of_week')
    help_text = "NOTA: Dopo aver modificato questi valori, è necessario riavviare il container 'scheduler' per applicare le modifiche."