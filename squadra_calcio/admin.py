from django.contrib import admin
from .models import Giocatore, Evento, Presenza, Campionato, SquadraClassifica

@admin.register(Giocatore)
class GiocatoreAdmin(admin.ModelAdmin):
    # Aggiunto modulo_golee_compilato alla visualizzazione
    list_display = ('nome_cognome', 'categoria', 'telefono_giocatore','telefono_genitore', 'modulo_golee_compilato', 'certificato_scaduto', 'attivo')
    list_filter = ('categoria', 'attivo', 'modulo_golee_compilato')
    search_fields = ('nome_cognome',)

@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'categoria_squadra', 'data', 'avversario', 'in_casa')
    list_filter = ('tipo', 'categoria_squadra')
    date_hierarchy = 'data'

@admin.register(Presenza)
class PresenzaAdmin(admin.ModelAdmin):
    # Sostituito registrato_da con firma_dispositivo
    list_display = ('giocatore', 'evento', 'presente', 'firma_dispositivo')
    list_filter = ('presente', 'evento__tipo', 'evento__categoria_squadra')
    search_fields = ('giocatore__nome_cognome',)
    
    # Se inserisci la presenza da PC, salva il tuo nome utente come "firma"
    def save_model(self, request, obj, form, change):
        if not obj.firma_dispositivo:
            obj.firma_dispositivo = f"Admin: {request.user.username}"
        obj.save()

admin.site.register(Campionato)
admin.site.register(SquadraClassifica)