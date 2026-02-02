from django.core.management.base import BaseCommand
from atleti.models import Scarpa
from atleti.utils import normalizza_scarpa

class Command(BaseCommand):
    help = 'Testa la normalizzazione delle scarpe e aggiorna il DB se richiesto'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Applica le modifiche al database',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        self.stdout.write("--- TEST NORMALIZZAZIONE SCARPE ---")
        
        scarpe = Scarpa.objects.all().order_by('brand', 'nome')
        count_changed = 0
        
        # Intestazione Tabella
        self.stdout.write(f"{'NOME ORIGINALE':<40} | {'ATTUALE DB':<20} | {'NUOVO CALCOLO'}")
        self.stdout.write("-" * 90)

        for s in scarpe:
            brand, nuovo_modello = normalizza_scarpa(s.nome)
            nuovo_modello = nuovo_modello.strip()
            
            # Verifica se cambia
            cambia = s.modello_normalizzato != nuovo_modello
            marker = "🔄 CAMBIA" if cambia else "✅ OK"
            colore = self.style.WARNING if cambia else self.style.SUCCESS
            
            self.stdout.write(colore(f"{s.nome[:40]:<40} | {str(s.modello_normalizzato)[:20]:<20} | {nuovo_modello}  {marker}"))
            
            if cambia and apply_changes:
                s.modello_normalizzato = nuovo_modello
                s.save()
                count_changed += 1

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"\nAggiornate {count_changed} scarpe nel database."))
        else:
            self.stdout.write(self.style.NOTICE(f"\nModalità DRY-RUN. {count_changed} scarpe verrebbero aggiornate."))
            self.stdout.write("Usa '--apply' per applicare le modifiche.")