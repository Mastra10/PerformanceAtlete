from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

class Command(BaseCommand):
    help = 'Diagnostica Fuso Orario e Parsing Date'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== DIAGNOSTICA TIMEZONE ==="))
        
        # 1. Configurazione Django
        self.stdout.write(f"TIME_ZONE (settings): {settings.TIME_ZONE}")
        self.stdout.write(f"USE_TZ (settings): {getattr(settings, 'USE_TZ', 'N/A')}")
        
        # 2. Orario Sistema
        now_sys = datetime.datetime.now()
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        self.stdout.write(f"Orario Sistema (Naive): {now_sys}")
        self.stdout.write(f"Orario UTC: {now_utc}")
        
        # 3. Test Parsing Europe/Rome
        self.stdout.write("\n=== TEST PARSING ===")
        input_str = "2026-02-09T12:30" # L'orario che ti dava problemi
        self.stdout.write(f"Input Form simulato: '{input_str}'")
        
        try:
            # Simuliamo cosa fa Django quando attiva il fuso orario
            tz = ZoneInfo("Europe/Rome")
            self.stdout.write(f"Caricamento ZoneInfo('Europe/Rome'): OK")
            
            dt_naive = datetime.datetime.strptime(input_str, "%Y-%m-%dT%H:%M")
            dt_rome = dt_naive.replace(tzinfo=tz)
            
            self.stdout.write(f"Interpretato come Roma: {dt_rome}")
            self.stdout.write(f"Offset rispetto UTC: {dt_rome.utcoffset()}")
            
            dt_utc = dt_rome.astimezone(datetime.timezone.utc)
            self.stdout.write(f"Salvato nel DB come UTC: {dt_utc}")
            
            if dt_utc.hour == 11 and dt_utc.minute == 30:
                self.stdout.write(self.style.SUCCESS("✅ CORRETTO: 12:30 Roma = 11:30 UTC (Inverno/Solare)"))
            else:
                self.stdout.write(self.style.WARNING(f"⚠️ ATTENZIONE: Conversione inattesa. Atteso 11:30 UTC, ottenuto {dt_utc.time()}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore critico Timezone: {e}"))
            self.stdout.write("Suggerimento: Assicurati che 'tzdata' sia installato nel container.")