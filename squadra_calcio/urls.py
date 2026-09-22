from django.urls import path
from . import views

urlpatterns = [
    path('api/giocatori/<str:categoria>/', views.api_get_giocatori, name='api_giocatori'),
    #path('api/presenza/salva/', views.api_salva_presenza, name='api_salva_presenza'),
    path('api/eventi/<str:categoria>/', views.api_get_eventi, name='api_eventi'),
    # path('api/crea_giocatore/', views.api_crea_giocatore, name='crea_giocatore'),
    # path('api/modifica_giocatore/<int:pk>/', views.api_modifica_giocatore, name='modifica_giocatore'),
    # path('api/elimina_giocatore/<int:pk>/', views.api_elimina_giocatore, name='elimina_giocatore'),
    path('api/statistiche_giocatore/<int:giocatore_id>/', views.api_statistiche_giocatore, name='api_statistiche_giocatore'),
    path('api/salva_foglio_presenze/', views.api_salva_foglio_presenze, name='api_salva_foglio_presenze'),
    path('api/presenze_data/<str:data_allenamento>/<str:tipo_evento>/', views.api_get_presenze_data, name='api_get_presenze_data'),
    path('api/statistiche_globali/<str:categoria>/', views.api_statistiche_globali, name='api_statistiche_globali'),
    path('api/date_eventi/<str:tipo_evento>/', views.api_get_date_eventi, name='api_get_date_eventi'),
    # ... le altre rotte ...
    path('api/crea_giocatore/', views.api_crea_giocatore, name='crea_giocatore'),
    path('api/modifica_giocatore/<int:giocatore_id>/', views.api_modifica_giocatore, name='modifica_giocatore'),
    path('api/elimina_giocatore/<int:giocatore_id>/', views.api_elimina_giocatore, name='elimina_giocatore'),
    path('api/elimina_foglio_presenze/<str:data_allenamento>/', views.api_elimina_foglio_presenze, name='api_elimina_foglio_presenze'),
    path('api/salva_log/', views.api_salva_log, name='api_salva_log'),
    path('api/logs/', views.api_get_logs, name='api_get_logs'),
    path('api/risultati/<str:categoria>/', views.api_risultati),
    path('api/elimina_risultato/<int:pk>/', views.api_elimina_risultato),
    path('api/allarmi_ack/', views.api_ack_allarme),
    path('api/analisi_ia/', views.api_analisi_ia, name='api_analisi_ia'),
    path('api/scouting/', views.api_scouting, name='api_scouting'),
    path('api/prenotazioni/', views.api_prenotazioni, name='api_prenotazioni'),
    path('api/prenotazioni/approva/<int:pk>/', views.api_approva_prenotazione, name='api_approva_prenotazione'),
    path('api/prenotazioni/elimina/<int:pk>/', views.api_elimina_prenotazione, name='api_elimina_prenotazione'),
    path('api/scouting/elimina/<int:pk>/', views.api_elimina_scouting, name='api_elimina_scouting'),
    path('api/salva_token_fcm/', views.api_salva_token_fcm, name='api_salva_token_fcm'),
    #path('api/api_check_update/', views.api_check_update, name='api_check_update'),
    path('api/check_update/', views.api_check_update, name='api_check_update'),
    # Aggiungi questa riga sotto le altre rotte API
    path('api/andamento_chart/<str:categoria>/', views.api_andamento_chart, name='api_andamento_chart'),
    path('monitoraggio/accessi/', views.pannello_accessi_web, name='dashboard_accessi'),
    # ...
]
