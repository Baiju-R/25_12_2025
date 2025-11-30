from django.contrib import admin
from .models import Donor, BloodDonate

@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ['get_name', 'bloodgroup', 'mobile']
    list_filter = ['bloodgroup']
    search_fields = ['user__first_name', 'user__last_name', 'mobile']

@admin.register(BloodDonate)
class BloodDonateAdmin(admin.ModelAdmin):
    list_display = ['donor', 'bloodgroup', 'unit', 'status', 'date']
    list_filter = ['bloodgroup', 'status', 'date']
    search_fields = ['donor__user__first_name', 'donor__user__last_name']
