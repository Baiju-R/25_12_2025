from django.urls import path
from . import views

urlpatterns = [
    path('patientlogin/', views.patientlogin_view, name='patientlogin'),
    path('patientsignup/', views.patientsignup_view, name='patientsignup'),
    path('dashboard/', views.patient_dashboard_view, name='patient-dashboard'),
    path('make-request/', views.patient_request_view, name='make-request'),
    path('my-request/', views.patient_request_history_view, name='my-request'),
]