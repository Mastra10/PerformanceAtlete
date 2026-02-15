from django import forms
from .models import Allenamento, CommentoAllenamento, Partecipazione, Team
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class AllenamentoForm(forms.ModelForm):
    # Forziamo i formati di input per datetime-local per evitare errori di parsing
    data_orario = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M')
    )

    passo_stimato = forms.CharField(
        required=False,
        label="Passo Stimato (min/km)",
        widget=forms.TextInput(attrs={'readonly': 'readonly', 'class': 'form-control bg-light', 'placeholder': 'Calcolato automaticamente...'})
    )

    class Meta:
        model = Allenamento
        fields = ['titolo', 'luogo', 'indirizzo', 'descrizione', 'data_orario', 'distanza_km', 'dislivello', 'tipo', 'tempo_stimato', 'visibilita', 'file_gpx', 'invitati', 'latitudine', 'longitudine']
        widgets = {
            'tempo_stimato': forms.TextInput(attrs={'placeholder': 'HH:MM:SS', 'class': 'form-control'}),
            'luogo': forms.TextInput(attrs={'placeholder': 'Cerca indirizzo o città...', 'class': 'form-control', 'autocomplete': 'off'}),
            'indirizzo': forms.TextInput(attrs={'placeholder': 'Via/Piazza specifica (opzionale)', 'class': 'form-control'}),
            'invitati': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'descrizione': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'latitudine': forms.HiddenInput(),
            'longitudine': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rendiamo il luogo obbligatorio come richiesto
        self.fields['luogo'].required = True
        
        # Filtra gli invitati escludendo admin e se stessi se necessario
        self.fields['invitati'].queryset = User.objects.all().order_by('first_name')
        # Rendiamo opzionali i campi che possono essere estratti dal GPX
        self.fields['distanza_km'].required = False
        self.fields['dislivello'].required = False
        
        # Riordiniamo i campi per mettere passo_stimato subito dopo tempo_stimato
        if 'tempo_stimato' in self.fields and 'passo_stimato' in self.fields:
            new_fields = {}
            for key, value in self.fields.items():
                new_fields[key] = value
                if key == 'tempo_stimato':
                    new_fields['passo_stimato'] = self.fields['passo_stimato']
            self.fields = new_fields


class CommentoForm(forms.ModelForm):
    class Meta:
        model = CommentoAllenamento
        fields = ['testo']
        widgets = {
            'testo': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Scrivi una domanda o un commento...'})
        }

class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['nome', 'descrizione', 'immagine']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descrizione': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

class InvitoTeamForm(forms.Form):
    utente = forms.ModelChoiceField(
        queryset=User.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Seleziona Utente da Invitare"
    )

class RegistrazioneUtenteForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True, label="Nome")
    last_name = forms.CharField(max_length=30, required=True, label="Cognome")
    email = forms.EmailField(required=True, label="Email")
    
    # Anti-Bot: Honeypot (Campo nascosto che i bot tendono a compilare)
    website_check = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'style': 'display:none;', 'tabindex': '-1', 'autocomplete': 'off'}),
        label="Lasciare vuoto"
    )
    
    # Anti-Bot: Domanda Matematica Semplice
    security_question = forms.IntegerField(
        label="Controllo Sicurezza: Quanto fa 3 + 4?",
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Inserisci il risultato (numero)'})
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        
    def clean_security_question(self):
        answer = self.cleaned_data.get('security_question')
        if answer != 7:
            raise forms.ValidationError("Risposta errata. Sei un robot?")
        return answer
        
    def clean(self):
        cleaned_data = super().clean()
        # Verifica Honeypot
        if cleaned_data.get('website_check'):
            raise forms.ValidationError("Spam rilevato.")
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user