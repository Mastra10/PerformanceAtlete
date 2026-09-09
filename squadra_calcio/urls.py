from django.urls import path
from . import views

urlpatterns = [
    path('api/giocatori/<str:categoria>/', views.api_get_giocatori, name='api_giocatori'),
    path('api/presenza/salva/', views.api_salva_presenza, name='api_salva_presenza'),
    path('api/giocatori/crea/', views.api_crea_giocatore, name='api_crea_giocatore'),
    path('api/eventi/<str:categoria>/', views.api_get_eventi, name='api_eventi'), # La nuova rotta!
    path('api/modifica_giocatore/<int:giocatore_id>/', views.api_modifica_giocatore, name='api_modifica_giocatore'),
    path('api/statistiche_giocatore/<int:giocatore_id>/', views.api_statistiche_giocatore, name='api_statistiche_giocatore'),
    path('api/elimina_giocatore/<int:giocatore_id>/', views.api_elimina_giocatore, name='api_elimina_giocatore'),
    path('api/salva_foglio_presenze/', views.api_salva_foglio_presenze),
    path('api/presenze_data/<str:data_allenamento>/<str:tipo_evento>/', views.api_get_presenze_data, name='api_get_presenze_data'),
    path('api/statistiche_globali/<str:categoria>/', views.api_statistiche_globali, name='api_statistiche_globali'),
    path('api/date_eventi/<str:tipo_evento>/', views.api_get_date_eventi, name='api_get_date_eventi'),
]
