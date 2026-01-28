from django.contrib import admin
from .models import Stock, BloodRequest
from .models import Feedback

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['bloodgroup', 'unit']
    list_filter = ['bloodgroup']

@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = ['patient_name', 'bloodgroup', 'unit', 'status', 'date']
    list_filter = ['bloodgroup', 'status', 'date']
    search_fields = ['patient_name', 'reason']

@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
     list_display = ('author_type', 'author_label', 'rating', 'feedback_for', 'is_public', 'created_at')
     list_filter = ('author_type', 'feedback_for', 'rating', 'is_public')
     search_fields = ('display_name', 'message', 'admin_reply')
