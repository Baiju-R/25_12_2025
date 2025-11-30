from django.contrib import admin
from .models import Stock, BloodRequest

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['bloodgroup', 'unit']
    list_filter = ['bloodgroup']

@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = ['patient_name', 'bloodgroup', 'unit', 'status', 'date']
    list_filter = ['bloodgroup', 'status', 'date']
    search_fields = ['patient_name', 'reason']
