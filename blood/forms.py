from django import forms
from . import models

class BloodForm(forms.ModelForm):
    class Meta:
        model = models.Stock
        fields = ['bloodgroup', 'unit']
        widgets = {
            'bloodgroup': forms.Select(choices=[
                ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
                ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-')
            ], attrs={'class': 'form-control'}),
            'unit': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'})
        }

class RequestForm(forms.ModelForm):
    class Meta:
        model = models.BloodRequest
        fields = ['patient_name', 'patient_age', 'reason', 'bloodgroup', 'unit']
        widgets = {
            'bloodgroup': forms.Select(choices=[
                ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
                ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-')
            ], attrs={'class': 'form-control'}),
            'unit': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'})
        }
