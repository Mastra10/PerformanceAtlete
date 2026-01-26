from django.apps import AppConfig
import os


class AtletiConfig(AppConfig):
    name = 'atleti'

    def ready(self):
        # Lo scheduler ora è gestito come servizio separato tramite il comando 'run_scheduler'
        pass
