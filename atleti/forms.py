from django import forms
from .models import Allenamento, CommentoAllenamento, Partecipazione
from django.contrib.auth.models import User

class AllenamentoForm(forms.ModelForm):
    class Meta:
        model = Allenamento
        fields = ['titolo', 'descrizione', 'data_orario', 'distanza_km', 'dislivello', 'tipo', 'tempo_stimato', 'visibilita', 'file_gpx', 'invitati']
        widgets = {
            'data_orario': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'tempo_stimato': forms.TextInput(attrs={'placeholder': 'HH:MM:SS', 'class': 'form-control'}),
            'invitati': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'descrizione': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra gli invitati escludendo admin e se stessi se necessario
        self.fields['invitati'].queryset = User.objects.all().order_by('first_name')
        # Rendiamo opzionali i campi che possono essere estratti dal GPX
        self.fields['distanza_km'].required = False
        self.fields['dislivello'].required = False

class CommentoForm(forms.ModelForm):
    class Meta:
        model = CommentoAllenamento
        fields = ['testo']
        widgets = {
            'testo': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Scrivi una domanda o un commento...'})
        }