from django import forms
from .models import Allenamento, CommentoAllenamento, Partecipazione
from django.contrib.auth.models import User

class AllenamentoForm(forms.ModelForm):
    # Forziamo i formati di input per datetime-local per evitare errori di parsing
    data_orario = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M')
    )

    class Meta:
        model = Allenamento
        fields = ['titolo', 'descrizione', 'data_orario', 'distanza_km', 'dislivello', 'tipo', 'tempo_stimato', 'visibilita', 'file_gpx', 'invitati']
        widgets = {
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