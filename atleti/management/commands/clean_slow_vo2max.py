from django.core.management.base import BaseCommand
from atleti.models import Attivita

class Command(BaseCommand):
    help = 'Pulisce il VO2max per attività con passo più lento di 9:30 min/km (570 sec/km)'

    def handle(self, *args, **options):
        self.stdout.write("Inizio pulizia attività lente...")
        
        # Filtriamo solo le attività che hanno un VO2max calcolato
        activities = Attivita.objects.filter(vo2max_stimato__isnull=False)
        count = 0
        
        for act in activities:
            if act.distanza > 0 and act.durata > 0:
                # Calcolo passo in secondi al km
                passo_sec_km = act.durata / (act.distanza / 1000)
                
                # Soglia: 9:30 min/km = 570 secondi
                if passo_sec_km > 570:
                    act.vo2max_stimato = None
                    act.save()
                    count += 1
                    
                    # Formattazione per log
                    mins = int(passo_sec_km // 60)
                    secs = int(passo_sec_km % 60)
                    self.stdout.write(f"Pulito ID {act.id} ({act.data.date()}): Passo {mins}:{secs:02d} > 9:30")
        
        self.stdout.write(self.style.SUCCESS(f"✅ Operazione completata! Pulite {count} attività."))