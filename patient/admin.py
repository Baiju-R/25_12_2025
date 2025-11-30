from django.contrib import admin
from .models import Patient

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['get_name', 'bloodgroup', 'mobile', 'disease']
    list_filter = ['bloodgroup', 'disease']
    search_fields = ['user__first_name', 'user__last_name', 'mobile']
