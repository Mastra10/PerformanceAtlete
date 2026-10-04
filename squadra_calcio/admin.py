from django.contrib import admin
from .models import (
    Giocatore, Evento, Presenza, Campionato, SquadraClassifica,
    CacheApi, LogConnessione, DispositivoToken, PrenotazioneCampo,
    SegnalazioneScouting, ProfiloMister, LogModifica, Risultato, AllarmeAck
)

@admin.register(Giocatore)
class GiocatoreAdmin(admin.ModelAdmin):
    list_display = ('nome_cognome', 'categoria', 'ruolo', 'telefono_giocatore', 'modulo_golee_compilato', 'certificato_scaduto', 'attivo')
    list_filter = ('categoria', 'ruolo', 'attivo', 'modulo_golee_compilato')
    search_fields = ('nome_cognome', 'telefono_giocatore', 'telefono_genitore')

@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'categoria_squadra', 'data', 'avversario', 'in_casa')
    list_filter = ('tipo', 'categoria_squadra', 'in_casa')
    date_hierarchy = 'data'
    search_fields = ('avversario', 'luogo')

@admin.register(Presenza)
class PresenzaAdmin(admin.ModelAdmin):
    list_display = ('giocatore', 'evento', 'presente', 'firma_dispositivo')
    list_filter = ('presente', 'evento__tipo', 'evento__categoria_squadra')
    search_fields = ('giocatore__nome_cognome', 'firma_dispositivo')
    
    def save_model(self, request, obj, form, change):
        if not obj.firma_dispositivo:
            obj.firma_dispositivo = f"Admin: {request.user.username}"
        obj.save()

@admin.register(Risultato)
class RisultatoAdmin(admin.ModelAdmin):
    list_display = ('data_partita', 'categoria', 'avversario', 'gol_fatti', 'gol_subiti', 'in_casa', 'convalidata')
    list_filter = ('categoria', 'convalidata', 'in_casa')
    date_hierarchy = 'data_partita'
    search_fields = ('avversario', 'marcatori')
    list_editable = ('convalidata',) # Ti permette di mettere/togliere la spunta direttamente dalla lista!

@admin.register(PrenotazioneCampo)
class PrenotazioneCampoAdmin(admin.ModelAdmin):
    list_display = ('data_ora_inizio', 'categoria_richiedente', 'avversario', 'stato', 'richiedente')
    list_filter = ('stato', 'categoria_richiedente')
    date_hierarchy = 'data_ora_inizio'
    search_fields = ('avversario', 'richiedente', 'note')

@admin.register(SegnalazioneScouting)
class SegnalazioneScoutingAdmin(admin.ModelAdmin):
    list_display = ('nome_giocatore', 'squadra_avversaria', 'categoria_avversaria', 'segnalatore', 'data_creazione')
    list_filter = ('categoria_avversaria',)
    search_fields = ('nome_giocatore', 'squadra_avversaria', 'segnalatore')

@admin.register(LogConnessione)
class LogConnessioneAdmin(admin.ModelAdmin):
    list_display = ('data_ora', 'utente', 'categoria', 'endpoint', 'metodo', 'status_code')
    list_filter = ('status_code', 'metodo', 'categoria')
    search_fields = ('utente', 'endpoint')
    date_hierarchy = 'data_ora'

@admin.register(LogModifica)
class LogModificaAdmin(admin.ModelAdmin):
    list_display = ('data_ora', 'utente', 'azione')
    list_filter = ('utente',)
    search_fields = ('utente', 'azione')
    date_hierarchy = 'data_ora'

@admin.register(DispositivoToken)
class DispositivoTokenAdmin(admin.ModelAdmin):
    list_display = ('utente', 'data_aggiornamento', 'token_fcm')
    search_fields = ('utente', 'token_fcm')

@admin.register(CacheApi)
class CacheApiAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'categoria', 'ultima_modifica')
    list_filter = ('endpoint', 'categoria')

@admin.register(ProfiloMister)
class ProfiloMisterAdmin(admin.ModelAdmin):
    list_display = ('user', 'categoria_gestita')
    search_fields = ('user__username', 'categoria_gestita')

@admin.register(AllarmeAck)
class AllarmeAckAdmin(admin.ModelAdmin):
    list_display = ('giocatore_id', 'chiave_allarme', 'data_ack')
    search_fields = ('chiave_allarme',)

admin.site.register(Campionato)
admin.site.register(SquadraClassifica)