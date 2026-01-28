from django import forms
from django.contrib.auth.models import User
from .models import Patient
from blood.utils.phone import normalize_phone_number

class PatientUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'password']
        widgets = {
            'password': forms.PasswordInput()
        }

class PatientForm(forms.ModelForm):
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]
    
    bloodgroup = forms.ChoiceField(choices=BLOOD_GROUP_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
    
    class Meta:
        model = Patient
        fields = ['age', 'bloodgroup', 'disease', 'doctorname', 'address', 'mobile', 'profile_pic']
        widgets = {
            'age': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '120'}),
            'disease': forms.TextInput(attrs={'class': 'form-control'}),
            'doctorname': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mobile': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_pic': forms.FileInput(attrs={'class': 'form-control-file'})
        }

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile')
        normalized = normalize_phone_number(mobile)
        if not normalized:
            raise forms.ValidationError('Enter a valid phone number (preferably with country code).')
        return normalized

class PatientRequestForm(forms.ModelForm):
    is_urgent = forms.BooleanField(required=False, label="Mark request as urgent (notifies nearby donors)")

    class Meta:
        model = Patient
        fields = [
            'age',
            'bloodgroup',
            'disease',
            'doctorname',
            'address',
            'mobile',
            'profile_pic',
            'is_urgent',
        ]

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile')
        normalized = normalize_phone_number(mobile)
        if not normalized:
            raise forms.ValidationError('Enter a valid phone number (preferably with country code).')
        return normalized


class PatientUserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'})
        }
