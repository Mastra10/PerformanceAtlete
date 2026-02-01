from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Crea un utente di test standard (non admin) per verificare i permessi'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username del nuovo utente')
        parser.add_argument('--password', type=str, default='testpass123', help='Password (default: testpass123)')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"L'utente '{username}' esiste già."))
            return

        user = User.objects.create_user(username=username, password=password)
        # is_staff e is_superuser sono False di default con create_user, ma confermiamo
        user.is_staff = False
        user.is_superuser = False
        user.save()

        self.stdout.write(self.style.SUCCESS(f"✅ Utente '{username}' creato con successo!"))
        self.stdout.write(f"   Password: {password}")
        self.stdout.write(f"   Tipo: Utente Standard (No Admin)")