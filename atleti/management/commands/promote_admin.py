from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Promuove un utente a Staff/Superuser per accedere alla Admin Zone'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, nargs='?', help='Username dell\'utente da promuovere')

    def handle(self, *args, **options):
        username = options['username']
        
        if not username:
            self.stdout.write(self.style.WARNING("Specifica uno username. Ecco gli utenti disponibili:"))
            for u in User.objects.all():
                status = " (Admin)" if u.is_staff else ""
                email = f" [{u.email}]" if u.email else ""
                self.stdout.write(f"- {u.username}{email}{status}")
            return

        try:
            user = User.objects.get(username=username)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f'✅ Utente "{username}" promosso ad Admin! Ora vedrai il tasto Log Scheduler.'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'❌ Utente "{username}" non trovato.'))