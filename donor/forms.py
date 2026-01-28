from django import forms
from django.contrib.auth.models import User
from .models import Donor, BloodDonate
from blood.utils.phone import normalize_phone_number

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
    latitude = forms.DecimalField(
        required=False,
        min_value=-90,
        max_value=90,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
        help_text='Optional. Example: 12.971598'
    )
    longitude = forms.DecimalField(
        required=False,
        min_value=-180,
        max_value=180,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
        help_text='Optional. Example: 77.594566'
    )
    
    class Meta:
        model = Donor
        fields = [
            'bloodgroup', 'address', 'mobile', 'latitude', 'longitude', 'zipcode', 'profile_pic',
            # Medical / eligibility (optional but recommended for smart matching)
            'sex', 'date_of_birth', 'weight_kg', 'hemoglobin_g_dl',
            'blood_pressure_systolic', 'blood_pressure_diastolic',
            'has_chronic_disease', 'chronic_disease_details',
            'on_medication', 'medication_details',
            'smokes',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mobile': forms.TextInput(attrs={'class': 'form-control'}),
            'zipcode': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_pic': forms.FileInput(attrs={'class': 'form-control-file'})
        }

    def clean(self):
        cleaned_data = super().clean()
        lat = cleaned_data.get('latitude')
        lng = cleaned_data.get('longitude')

        if (lat is None) != (lng is None):
            raise forms.ValidationError(
                'Please provide both latitude and longitude or leave both blank.'
            )

        return cleaned_data

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile')
        normalized = normalize_phone_number(mobile)
        if not normalized:
            raise forms.ValidationError('Enter a valid phone number (preferably with country code).')
        return normalized

class BloodDonateForm(forms.ModelForm):
    class Meta:
        model = BloodDonate
        fields = ['bloodgroup', 'unit', 'disease', 'age']


class DonorUserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'})
        }
