from django import forms
from django.contrib.auth.models import User
from .models import Donor, BloodDonate

class DonorUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'password']
        widgets = {
            'password': forms.PasswordInput()
        }

class DonorForm(forms.ModelForm):
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
        model = Donor
        fields = ['bloodgroup', 'address', 'mobile', 'profile_pic']
        widgets = {
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mobile': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_pic': forms.FileInput(attrs={'class': 'form-control-file'})
        }

class BloodDonateForm(forms.ModelForm):
    class Meta:
        model = BloodDonate
        fields = ['bloodgroup', 'unit', 'disease', 'age']
