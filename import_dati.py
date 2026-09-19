import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

admins = [
    {"username": "Mastra10", "password": "PasswordSicura123!"}, # Cambia le password!
    {"username": "Francesco11", "password": "PasswordSicura123!"}
]

for admin_data in admins:
    # update_or_create non va bene per le password, usiamo get_or_create
    user, created = User.objects.get_or_create(username=admin_data["username"])
    if created:
        user.set_password(admin_data["password"])
        user.is_superuser = True
        user.is_staff = True
        user.save()
        print(f"✅ Creato Super Admin: {user.username}")
    else:
        print(f"⚠️ L'utente {user.username} esiste già.")
    
    # Genera o recupera il Token per questo utente
    token, _ = Token.objects.get_or_create(user=user)
    print(f"🔑 Token per {user.username}: {token.key}")