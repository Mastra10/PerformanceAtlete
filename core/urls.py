"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from atleti.views import home
from atleti import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.contrib.auth import views as auth_views
from atleti.views import statistiche_dispositivi 


urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    # Override per login cancellato (Standard Allauth e Path specifico segnalato)
    path('accounts/social/login/cancelled/', views.login_cancelled, name='socialaccount_login_cancelled'),
    path('accounts/3rdparty/login/cancelled/', views.login_cancelled),
    
    path('accounts/', include('allauth.urls')), # Gestisce tutto il flusso login/logout
    path('', home, name='home'), # Questo gestisce l'indirizzo http://localhost:8000/
    path('sync/', views.sincronizza_strava, name='strava_sync'),
    path('ricalcola-statistiche/', views.ricalcola_statistiche, name='ricalcola_statistiche'),
    path('calcola-vo2max/', views.calcola_vo2max, name='calcola_vo2max'),
    path('grafici/', views.grafici_atleta, name='grafici'),
    path('impostazioni/', views.impostazioni, name='impostazioni'),
    path('aggiorna-profilo/', views.aggiorna_dati_profilo, name='aggiorna_profilo'),
    path('pulisci-db/', views.elimina_attivita_anomale, name='pulisci_db'),
    path('export-csv/', views.export_csv, name='export_csv'),
    path('export-profile-csv/', views.export_profile_csv, name='export_profile_csv'),
    path('atleti/', views.riepilogo_atleti, name='riepilogo_atleti'),
    path('atleti/analisi-classifica-ai/', views.analisi_classifica_ai, name='analisi_classifica_ai'),
    path('gare/', views.gare_atleta, name='gare_atleta'),
    path('gare/analisi/', views.analisi_gare_ai, name='analisi_gare_ai'),
    path('coach/', views.dashboard_coach, name='dashboard_coach'),
    path('atleta/<str:username>/', views.dashboard_atleta, name='dashboard_atleta'),
    path('coach/analisi/', views.analisi_coach_gemini, name='analisi_coach_gemini'),
    path('scheduler-logs/', views.scheduler_logs, name='scheduler_logs'),
    path('run-task/<str:task_id>/', views.run_task_manually, name='run_task_manually'),
    path('scheduler-logs-update/', views.scheduler_logs_update, name='scheduler_logs_update'),
    path('reset-task/<str:task_id>/', views.reset_task_trigger, name='reset_task_trigger'),
    path('impersonate/<str:username>/', views.impersonate_user, name='impersonate_user'),
    path('analisi-ai/', views.analisi_gemini, name='analisi_gemini'),
    path('api/hide-home-notice/', views.hide_home_notice, name='hide_home_notice'),
    path('api/login/', views.api_login, name='api_login'),
    path('api/dashboard/', views.api_get_dashboard, name='api_get_dashboard'),
    path('api/workouts/', views.api_list_workouts, name='api_list_workouts'),
    path('api/workouts/create/', views.api_create_workout, name='api_create_workout'),
    path('api/workouts/<int:pk>/', views.api_workout_detail, name='api_workout_detail'),
    path('api/workouts/<int:pk>/action/', views.api_workout_action, name='api_workout_action'),
    path('api/workouts/<int:pk>/comment/', views.api_workout_comment, name='api_workout_comment'),
    path('api/coach/dashboard/', views.api_coach_dashboard, name='api_coach_dashboard'),
    path('api/athletes/summary/', views.api_athletes_summary, name='api_athletes_summary'),
    path('api/teams/', views.api_team_list, name='api_team_list'),
    path('guida/', views.guida_utente, name='guida_utente'),
    path('confronto/', views.confronto_attivita, name='confronto_attivita'),
    path('attrezzatura/', views.attrezzatura_scarpe, name='attrezzatura_scarpe'),
    path('registrazione/', views.registrazione, name='registrazione'),
    path('login-standard/', views.login_standard, name='login_standard'),
    path('dispositivi/', statistiche_dispositivi, name='statistiche_dispositivi'),
    path('statistiche-log/', views.statistiche_log, name='statistiche_log'),
    
    # --- ALLENAMENTI ---
    path('allenamenti/', views.lista_allenamenti, name='lista_allenamenti'),
    path('allenamenti/storico/', views.storico_allenamenti, name='storico_allenamenti'),
    path('allenamenti/nuovo/', views.crea_allenamento, name='crea_allenamento'),
    path('allenamenti/<int:pk>/', views.dettaglio_allenamento, name='dettaglio_allenamento'),
    path('allenamenti/partecipazione/<int:pk>/<str:action>/', views.gestisci_partecipazione, name='gestisci_partecipazione'),
    path('allenamenti/modifica/<int:pk>/', views.modifica_allenamento, name='modifica_allenamento'),
    path('allenamenti/elimina/<int:pk>/', views.elimina_allenamento, name='elimina_allenamento'),
    path('notifica-letta/<int:pk>/', views.segna_notifica_letta, name='segna_notifica_letta'),
    path('allenamenti/ics/<int:pk>/', views.download_allenamento_ics, name='download_allenamento_ics'),
    path('allenamenti/gpx/<int:pk>/', views.download_allenamento_gpx, name='download_allenamento_gpx'),

    # --- TEAM / GRUPPI ---
    path('team/crea/', views.crea_team, name='crea_team'),
    path('team/gestisci/<int:team_id>/', views.gestisci_team, name='gestisci_team'),
    path('team/elimina/<int:team_id>/', views.elimina_team, name='elimina_team'),
    path('team/switch/<int:team_id>/', views.switch_team, name='switch_team'),
    path('team/richiedi/<int:team_id>/', views.richiedi_adesione_team, name='richiedi_adesione_team'),
    path('team/invito/<int:richiesta_id>/<str:azione>/', views.gestisci_invito_utente, name='gestisci_invito_utente'),
    path('team/gestisci/<int:richiesta_id>/<str:azione>/', views.gestisci_adesione_team, name='gestisci_adesione_team'),
    path('team/image/<int:team_id>/', views.serve_team_image, name='serve_team_image'),
]


if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    