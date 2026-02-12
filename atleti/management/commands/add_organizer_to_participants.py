from django.core.management.base import BaseCommand
from atleti.models import Allenamento, Partecipazione

class Command(BaseCommand):
    help = 'Aggiunge il creatore dell\'allenamento alla lista dei partecipanti se mancante (fix retroattivo)'

    def handle(self, *args, **options):
        self.stdout.write("Inizio controllo allenamenti esistenti...")
        count = 0
        allenamenti = Allenamento.objects.all()
        
        for a in allenamenti:
            # Verifica se esiste già una partecipazione per il creatore
            # Se non c'è, la crea automaticamente come 'Approvata'
            obj, created = Partecipazione.objects.get_or_create(
                allenamento=a,
                atleta=a.creatore,
                defaults={'stato': 'Approvata'}
            )
            
            if created:
                self.stdout.write(f" -> Aggiunto organizzatore {a.creatore.username} a '{a.titolo}' ({a.data_orario.date()})")
                count += 1
        
        self.stdout.write(self.style.SUCCESS(f"Operazione completata. Aggiornati {count} allenamenti."))