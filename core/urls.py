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


urlpatterns = [
    path('admin/', admin.site.urls),
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
    path('atleti/', views.riepilogo_atleti, name='riepilogo_atleti'),
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
    path('guida/', views.guida_utente, name='guida_utente'),
    path('confronto/', views.confronto_attivita, name='confronto_attivita'),
    path('attrezzatura/', views.attrezzatura_scarpe, name='attrezzatura_scarpe'),
    path('accesso-diretto/', auth_views.LoginView.as_view(template_name='atleti/login_standard.html'), name='login_standard'),
]


if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()