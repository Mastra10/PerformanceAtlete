from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('atleti', '0026_scarpa_retired'),
    ]

    operations = [
        migrations.AddField(
            model_name='profiloatleta',
            name='hide_home_notice',
            field=models.BooleanField(default=False, verbose_name='Nascondi avviso home'),
        ),
    ]
