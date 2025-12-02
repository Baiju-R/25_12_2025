import json
import logging
from collections import defaultdict, OrderedDict
from copy import deepcopy
from datetime import date, timedelta, datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum, Q, Count, Max
from django.db.models.functions import TruncMonth
from django.http import HttpResponseRedirect, Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.templatetags.static import static
from django.utils import timezone

try:
    import folium  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    folium = None

from . import forms, models
from .services.geocoding import geocode_address
from .services import sms as sms_service
from .utils.sms_sender import send_sms
from donor import forms as dforms
from donor import models as dmodels
from patient import forms as pforms
from patient import models as pmodels

logger = logging.getLogger(__name__)


CHATBOT_FAQ = [
    {
        "category": "Getting Started",
        "icon": "rocket",
        "audience": "Everyone",
        "items": [
            {
                "id": "project-setup",
                "question": "How do I set up BloodBridge locally?",
                "answer": (
                    "Create/activate your virtual environment, install requirements, run migrations, "
                    "and then start the Django development server. The sqlite demo DB ships with data, "
                    "but you can reseed it any time using our management command."
                ),
                "keywords": [
                    "setup project",
                    "local install",
                    "runserver",
                    "migrations",
                    "requirements",
                    "seed data"
                ],
                "next_steps": [
                    "python -m pip install -r requirements.txt",
                    "py manage.py migrate",
                    "py manage.py seed_demo_data --purge --seed=123",
                    "py manage.py runserver"
                ],
                "links": [
                    {"label": "README setup guide", "url": "#readme"},
                    {"label": "Demo data command", "url": "#seed"}
                ],
                "audience": "New contributors"
            },
            {
                "id": "account-types",
                "question": "What roles exist and how do logins work?",
                "answer": (
                    "We keep three personas: Admin (superuser), Donor (group DONOR) and Patient (group PATIENT). "
                    "Admins manage approvals, donors can donate or request units, and patients can request units."
                ),
                "keywords": [
                    "roles",
                    "admin login",
                    "donor login",
                    "patient login",
                    "signup",
                    "groups"
                ],
                "next_steps": [
                    "Use /donor/signup/ or /patient/signup/ for self-service onboarding",
                    "Admins create via `py manage.py createsuperuser`",
                    "Each seeded demo user shares the password DemoPass123!"
                ],
                "links": [
                    {"label": "Donor signup", "url": "/donor/signup/"},
                    {"label": "Patient signup", "url": "/patient/signup/"}
                ],
                "audience": "Everyone"
            },
            {
                "id": "quick-request",
                "question": "Can visitors request blood without an account?",
                "answer": (
                    "Yes. The Quick Request form collects the bare minimum and creates a pending BloodRequest. "
                    "Admins see it in their queue just like authenticated requests."
                ),
                "keywords": [
                    "guest request",
                    "anonymous",
                    "quick request",
                    "emergency form",
                    "without account"
                ],
                "next_steps": [
                    "Navigate to /quick-request/",
                    "Fill in patient details, group, units, and contact info",
                    "Watch your phone or email for admin follow-up"
                ],
                "links": [
                    {"label": "Quick request", "url": "/quick-request/"}
                ],
                "audience": "Public visitors"
            }
        ]
    },
    {
        "category": "Donor Experience",
        "icon": "hand-holding-heart",
        "audience": "Donors",
        "items": [
            {
                "id": "donate-flow",
                "question": "How do I record a donation?",
                "answer": (
                    "After logging in as a donor, open the Donate Blood form, complete health screening fields, "
                    "and submit. The request stays Pending until an admin reviews it."
                ),
                "keywords": [
                    "record donation",
                    "submit donation",
                    "donor form",
                    "health screening",
                    "donation units"
                ],
                "next_steps": [
                    "Log in at /donor/donorlogin/",
                    "Open the Donate Blood card on your dashboard",
                    "Submit the form with units (200-500ml) and condition details"
                ],
                "links": [
                    {"label": "Donor dashboard", "url": "/donor/donor-dashboard/"}
                ],
                "audience": "Donors"
            },
            {
                "id": "donor-requests",
                "question": "Can donors also request blood?",
                "answer": (
                    "Yes. Donors can create self-serve requests (Request Blood tab). We record them as "
                    "BloodRequest rows with `request_by_donor` populated so admins can fast-track approvals."
                ),
                "keywords": [
                    "donor request blood",
                    "self request",
                    "request tab",
                    "make request",
                    "fast track"
                ],
                "next_steps": [
                    "Go to Donor > Request Blood",
                    "Specify recipient details and urgency",
                    "Track approval state on the history page"
                ],
                "links": [
                    {"label": "Donor request history", "url": "/donor/request-history/"}
                ],
                "audience": "Donors"
            },
            {
                "id": "donor-metrics",
                "question": "Where do I see my donation metrics?",
                "answer": (
                    "The donor dashboard aggregates approved units, pending requests, and latest activity. "
                    "Use it before events to download history or confirm eligibility."
                ),
                "keywords": [
                    "donation metrics",
                    "donor stats",
                    "dashboard charts",
                    "history",
                    "eligibility"
                ],
                "next_steps": [
                    "Visit /donor/donor-dashboard/",
                    "Use the timeline + charts to monitor progress",
                    "Export or screenshot for campaign reporting"
                ],
                "links": [],
                "audience": "Donors"
            }
        ]
    },
    {
        "category": "Patient Journey",
        "icon": "heartbeat",
        "audience": "Patients",
        "items": [
            {
                "id": "patient-request",
                "question": "How do patients request blood units?",
                "answer": (
                    "Patients submit requests from their dashboard. Each request tracks reason, units, "
                    "and auto-notifies admins. Status updates appear in the history view."
                ),
                "keywords": [
                    "patient request",
                    "make request",
                    "blood units",
                    "patient form",
                    "submit request"
                ],
                "next_steps": [
                    "Sign in via /patient/patientlogin/",
                    "Open Make Request",
                    "Submit the form and monitor the My Requests table"
                ],
                "links": [
                    {"label": "Patient dashboard", "url": "/patient/patient-dashboard/"}
                ],
                "audience": "Patients"
            },
            {
                "id": "patient-statuses",
                "question": "What do Pending, Approved, Rejected mean?",
                "answer": (
                    "Pending = waiting for admin review, Approved = units have been allocated in stock, "
                    "Rejected = admin could not fulfill (usually not enough stock)."
                ),
                "keywords": [
                    "pending meaning",
                    "approved meaning",
                    "status definitions",
                    "request status",
                    "rejected reason"
                ],
                "next_steps": [
                    "Use dashboard filters to focus on critical requests",
                    "If a request was rejected due to stock, consider editing units",
                    "Contact admin via the support note if urgent"
                ],
                "links": [],
                "audience": "Patients"
            },
            {
                "id": "patient-account",
                "question": "Do patients need admin approval to sign up?",
                "answer": (
                    "No. Patient signups are auto-approved. Once registered, patients can log in immediately "
                    "and start creating requests."
                ),
                "keywords": [
                    "patient signup",
                    "account approval",
                    "auto approval",
                    "register patient",
                    "patient onboarding"
                ],
                "next_steps": [
                    "Register via /patient/signup/",
                    "Confirm your blood group + doctor info",
                    "Head to Make Request"
                ],
                "links": [],
                "audience": "Patients"
            }
        ]
    },
    {
        "category": "Admin Operations",
        "icon": "cogs",
        "audience": "Admins",
        "items": [
            {
                "id": "approvals",
                "question": "How do admins approve donations and requests?",
                "answer": (
                    "Use the Admin Dashboard cards: Donations and Requests each have Approve/Reject buttons. "
                    "Approving donations increases stock; approving requests deducts stock automatically."
                ),
                "keywords": [
                    "approve donation",
                    "approve request",
                    "admin dashboard",
                    "stock update",
                    "review workflow"
                ],
                "next_steps": [
                    "Navigate to /admin-donation/ or /admin-request/",
                    "Inspect health/medical notes before acting",
                    "Watch stock widgets update in real time"
                ],
                "links": [
                    {"label": "Admin dashboard", "url": "/admin-dashboard/"}
                ],
                "audience": "Admins"
            },
            {
                "id": "analytics",
                "question": "Where can I find insights and charts?",
                "answer": (
                    "The Admin Analytics page aggregates approval stats, stock burn-down, donor leaders, and "
                    "time-bound filters so you can prep reports quickly."
                ),
                "keywords": [
                    "analytics",
                    "charts",
                    "reports",
                    "insights",
                    "dashboard metrics"
                ],
                "next_steps": [
                    "Visit /admin-analytics/",
                    "Select a date window and status filters",
                    "Export charts via the built-in download buttons"
                ],
                "links": [],
                "audience": "Admins"
            },
            {
                "id": "data-seeding",
                "question": "How do I refresh the demo dataset?",
                "answer": (
                    "Run the seed_demo_data management command. It creates 75-100 donors/patients, adds stock, "
                    "and generates donation/request histories for dashboards."
                ),
                "keywords": [
                    "seed data",
                    "demo dataset",
                    "populate database",
                    "management command",
                    "test data"
                ],
                "next_steps": [
                    "py manage.py seed_demo_data --purge --seed=123",
                    "Log in with any generated user (DemoPass123!)",
                    "Review dashboards for the new data"
                ],
                "links": [],
                "audience": "Admins"
            }
        ]
    },
    {
        "category": "Troubleshooting & Support",
        "icon": "life-ring",
        "audience": "Everyone",
        "items": [
            {
                "id": "login-issues",
                "question": "I forgot my password or can’t log in",
                "answer": (
                    "Use Django’s admin panel to reset credentials, or for demo accounts rerun the seeding "
                    "command to regenerate logins."
                ),
                "keywords": [
                    "forgot password",
                    "reset password",
                    "login issue",
                    "credentials",
                    "account locked"
                ],
                "next_steps": [
                    "Admin: py manage.py changepassword <username>",
                    "Demo: rerun seed_demo_data to reset creds",
                    "Ensure caps lock isn’t on and username is exact"
                ],
                "links": [],
                "audience": "Everyone"
            },
            {
                "id": "stock-sync",
                "question": "Stock numbers look incorrect",
                "answer": (
                    "Remember stock mutates only when admins approve donations/requests or edit stock manually. "
                    "Audit recent approvals to verify unit math."
                ),
                "keywords": [
                    "stock mismatch",
                    "inventory issue",
                    "unit count",
                    "stock incorrect",
                    "stock audit"
                ],
                "next_steps": [
                    "Check Admin > Blood to override manually if needed",
                    "Review latest approvals for large unit changes",
                    "Use analytics charts to spot anomalies"
                ],
                "links": [],
                "audience": "Admins"
            },
            {
                "id": "support-contact",
                "question": "How do I contact the maintainers?",
                "answer": (
                    "File an issue on the repository or email the BloodBridge maintainers. Mention logs, steps "
                    "to reproduce, and screenshots if relevant."
                ),
                "keywords": [
                    "contact maintainer",
                    "support",
                    "github issue",
                    "help",
                    "email"
                ],
                "next_steps": [
                    "Open GitHub issues tab",
                    "Share stack traces + describe environment",
                    "Attach screenshots of dashboards if UI related"
                ],
                "links": [
                    {"label": "Project repo", "url": "https://github.com/Baiju-R/final_year_project"}
                ],
                "audience": "Everyone"
            }
        ]
    }
]

CHATBOT_PROMPTS = [
    "How do I run the project?",
    "Create donor account",
    "Submit patient blood request",
    "Approve a donation",
    "Refresh demo data",
    "Fix login issues",
    "Understand request statuses",
    "Contact maintainers"
]


def _auto_assign_coordinates(limit: int | None = None):
    missing_donors_qs = (
        dmodels.Donor.objects
        .filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))
        .exclude(address__isnull=True)
        .exclude(address__exact='')
        .order_by('id')
    )
    if limit:
        missing_donors_qs = missing_donors_qs[:limit]
    donors = list(missing_donors_qs)
    if not donors:
        return 0, []
    allow_remote = getattr(settings, 'GEOCODER_ALLOW_REMOTE', True)
    country_bias = getattr(settings, 'GEOCODER_COUNTRY_BIAS', None)
    successful = 0
    failures = []
    for donor in donors:
        result = geocode_address(donor.address, country_bias=country_bias, allow_remote=allow_remote)
        if not result:
            failures.append(donor.get_name)
            continue
        donor.latitude = result.latitude
        donor.longitude = result.longitude
        donor.location_verified = False
        donor.save(update_fields=['latitude', 'longitude', 'location_verified'])
        successful += 1
    return successful, failures

def home_view(request):
    x = models.Stock.objects.all()
    if len(x) == 0:
        blood_groups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
        for bg in blood_groups:
            blood = models.Stock()
            blood.bloodgroup = bg
            blood.save()

    if request.user.is_authenticated:
        return HttpResponseRedirect('afterlogin')  

    top_donor_spotlight = []
    placeholder_avatar = static('image/homepage.png')

    approved_donations = dmodels.BloodDonate.objects.filter(status='Approved')
    donor_leaders = (
        approved_donations
        .values('donor_id')
        .annotate(
            total_units=Sum('unit'),
            donation_count=Count('id'),
            last_donation=Max('date')
        )
        .order_by('-total_units')[:3]
    )

    donor_map = dmodels.Donor.objects.select_related('user').in_bulk([entry['donor_id'] for entry in donor_leaders])

    for rank, entry in enumerate(donor_leaders, start=1):
        donor = donor_map.get(entry['donor_id'])
        if not donor:
            continue
        top_donor_spotlight.append({
            'rank': rank,
            'name': donor.get_name,
            'bloodgroup': donor.bloodgroup,
            'total_units': int(entry['total_units'] or 0),
            'donation_count': entry['donation_count'] or 0,
            'last_donation': entry['last_donation'],
            'profile_pic_url': donor.profile_pic.url if donor.has_profile_pic else placeholder_avatar,
        })

    context = {
        'top_donor_spotlight': top_donor_spotlight,
        'has_top_donors': bool(top_donor_spotlight),
    }

    return render(request, 'blood/index.html', context)

def adminlogin_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect('admin-dashboard')
        else:
            messages.error(request, 'Invalid admin credentials.')
    
    return render(request, 'blood/adminlogin.html')

def afterlogin_view(request):
    if request.user.is_superuser:
        return redirect('admin-dashboard')
    elif request.user.groups.filter(name='DONOR').exists():
        return redirect('donor-dashboard')
    elif request.user.groups.filter(name='PATIENT').exists():
        return redirect('patient-dashboard')
    else:
        return redirect('home')

def logout_view(request):
    logout(request)
    return redirect('home')

@login_required
def admin_dashboard_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    # Fix total unit calculation
    totalunit = models.Stock.objects.aggregate(Sum('unit'))
    total_blood_unit = totalunit['unit__sum'] if totalunit['unit__sum'] else 0
    
    # Fix donor count calculation
    total_donors = dmodels.Donor.objects.count()
    
    # Fix request calculations
    total_requests = models.BloodRequest.objects.count()
    approved_requests = models.BloodRequest.objects.filter(status='Approved').count()
    pending_requests = models.BloodRequest.objects.filter(status='Pending').count()
    rejected_requests = models.BloodRequest.objects.filter(status='Rejected').count()
    
    # Fix patient count
    total_patients = pmodels.Patient.objects.count()
    
    # Fix donation calculations
    total_donations = dmodels.BloodDonate.objects.count()
    approved_donations = dmodels.BloodDonate.objects.filter(status='Approved').count()
    
    dict={
        'A1':models.Stock.objects.get(bloodgroup="A+"),
        'A2':models.Stock.objects.get(bloodgroup="A-"),
        'B1':models.Stock.objects.get(bloodgroup="B+"),
        'B2':models.Stock.objects.get(bloodgroup="B-"),
        'AB1':models.Stock.objects.get(bloodgroup="AB+"),
        'AB2':models.Stock.objects.get(bloodgroup="AB-"),
        'O1':models.Stock.objects.get(bloodgroup="O+"),
        'O2':models.Stock.objects.get(bloodgroup="O-"),
        'totaldonors': total_donors,
        'totalpatients': total_patients,
        'totalbloodunit': total_blood_unit,
        'totalrequest': total_requests,
        'totalapprovedrequest': approved_requests,
        'totalpendingrequest': pending_requests,
        'totalrejectedrequest': rejected_requests,
        'totaldonations': total_donations,
        'totalapproveddonations': approved_donations,
    }
    return render(request, 'blood/admin_dashboard.html', context=dict)

@login_required
def admin_blood_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    dict={
        'bloodForm':forms.BloodForm(),
        'A1':models.Stock.objects.get(bloodgroup="A+"),
        'A2':models.Stock.objects.get(bloodgroup="A-"),
        'B1':models.Stock.objects.get(bloodgroup="B+"),
        'B2':models.Stock.objects.get(bloodgroup="B-"),
        'AB1':models.Stock.objects.get(bloodgroup="AB+"),
        'AB2':models.Stock.objects.get(bloodgroup="AB-"),
        'O1':models.Stock.objects.get(bloodgroup="O+"),
        'O2':models.Stock.objects.get(bloodgroup="O-"),
    }
    if request.method=='POST':
        bloodForm=forms.BloodForm(request.POST)
        if bloodForm.is_valid() :        
            bloodgroup=bloodForm.cleaned_data['bloodgroup']
            stock=models.Stock.objects.get(bloodgroup=bloodgroup)
            stock.unit=bloodForm.cleaned_data['unit']
            stock.save()
        return redirect('admin-blood')
    return render(request, 'blood/admin_blood.html', context=dict)


@login_required
def admin_donor_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    donors = dmodels.Donor.objects.all()
    return render(request, 'blood/admin_donor.html', {'donors': donors})


@login_required
def admin_donor_map_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')

    if request.method == 'POST':
        intent = request.POST.get('intent')
        if intent == 'bulk_geocode':
            limit_value = None
            limit_raw = request.POST.get('limit')
            if limit_raw:
                try:
                    limit_value = max(1, min(50, int(limit_raw)))
                except ValueError:
                    limit_value = None
            success_count, failed_names = _auto_assign_coordinates(limit_value)
            if success_count:
                messages.success(request, f"Pinned {success_count} donor{'s' if success_count != 1 else ''} using their addresses.")
            if failed_names:
                preview = ', '.join(failed_names[:3])
                if len(failed_names) > 3:
                    preview += ', …'
                messages.warning(request, f"Could not resolve {len(failed_names)} donor address{'es' if len(failed_names) != 1 else ''}: {preview}")
            if success_count == 0 and not failed_names:
                messages.info(request, 'All donors are already mapped!')
            return redirect('admin-donor-map')

        donor_id = request.POST.get('donor_id')
        action = request.POST.get('action')
        try:
            donor = dmodels.Donor.objects.get(id=donor_id)
        except dmodels.Donor.DoesNotExist:
            messages.error(request, 'Selected donor was not found.')
        else:
            donor.location_verified = action == 'verify'
            donor.save(update_fields=['location_verified'])
            verb = 'verified' if donor.location_verified else 'marked as pending'
            messages.success(request, f"{donor.get_name} location {verb} for the map.")
        return redirect('admin-donor-map')

    donor_qs = (
        dmodels.Donor.objects.select_related('user')
        .annotate(
            total_units=Sum('blooddonate__unit', filter=Q(blooddonate__status='Approved')),
            total_donations=Count('blooddonate', filter=Q(blooddonate__status='Approved')),
        )
    )
    donors = list(donor_qs)

    marker_payload = []
    lat_accumulator = 0
    lng_accumulator = 0
    for donor in donors:
        if donor.latitude is not None and donor.longitude is not None:
            lat = float(donor.latitude)
            lng = float(donor.longitude)
            lat_accumulator += lat
            lng_accumulator += lng
            marker_payload.append({
                'id': donor.id,
                'name': donor.get_name,
                'username': donor.user.username,
                'bloodgroup': donor.bloodgroup,
                'units': float(donor.total_units or 0),
                'donations': donor.total_donations or 0,
                'mobile': donor.mobile,
                'address': donor.address,
                'latitude': lat,
                'longitude': lng,
                'location_verified': donor.location_verified,
            })

    marker_count = len(marker_payload)
    if marker_count:
        map_center = {
            'lat': round(lat_accumulator / marker_count, 6),
            'lng': round(lng_accumulator / marker_count, 6),
        }
    else:
        map_center = {'lat': 20.5937, 'lng': 78.9629}  # Default center (India)

    verified_count = sum(1 for marker in marker_payload if marker['location_verified'])
    without_coordinates = sum(1 for donor in donors if donor.latitude is None or donor.longitude is None)
    donors_with_coordinates = [donor for donor in donors if donor.latitude is not None and donor.longitude is not None]
    folium_map_html = None
    folium_error = None
    if folium:
        base_location = [map_center['lat'], map_center['lng']]
        folium_map = folium.Map(
            location=base_location,
            zoom_start=2,
            control_scale=True,
            tiles=None,
            world_copy_jump=True,
        )
        folium.TileLayer(
            tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attr='&copy; OpenStreetMap contributors',
            name='OpenStreetMap',
            control=False,
            max_zoom=19,
        ).add_to(folium_map)
        marker_bounds = []
        for marker in marker_payload:
            coords = (marker['latitude'], marker['longitude'])
            marker_bounds.append(coords)
            popup_html = (
                f"<strong>{marker['name']}</strong><br/>"
                f"{marker['bloodgroup']} • {int(marker['units'])} ml<br/>"
                f"{marker['address']}<br/>"
                f"<small>{'Verified' if marker['location_verified'] else 'Pending'} location</small>"
            )
            folium.CircleMarker(
                location=coords,
                radius=7 if marker['location_verified'] else 5,
                color='#047857' if marker['location_verified'] else '#f59e0b',
                fill=True,
                fill_color='#047857' if marker['location_verified'] else '#f59e0b',
                fill_opacity=0.9,
                weight=2,
            ).add_child(folium.Popup(popup_html, max_width=260)).add_to(folium_map)
        if len(marker_bounds) > 1:
            folium_map.fit_bounds(marker_bounds, padding=(25, 25))
        elif marker_bounds:
            folium_map.location = marker_bounds[0]
            folium_map.zoom_start = 6
        folium_map_html = folium_map._repr_html_()
    elif marker_payload:
        folium_error = 'Install folium to enable the Python-rendered global donor map.'
    context = {
        'map_data': marker_payload,
        'map_center': map_center,
        'total_donors': len(donors),
        'pin_ready': marker_count,
        'verified_count': verified_count,
        'pending_count': marker_count - verified_count,
        'without_coordinates': without_coordinates,
        'donors': donors_with_coordinates,
        'folium_map': folium_map_html,
        'folium_error': folium_error,
    }
    return render(request, 'blood/admin_donor_map.html', context)

@login_required
def update_donor_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    donor = dmodels.Donor.objects.get(id=pk)
    user = User.objects.get(id=donor.user_id)
    if request.method == 'POST':
        userForm = dforms.DonorUserUpdateForm(request.POST, instance=user)
        donorForm = dforms.DonorForm(request.POST, request.FILES, instance=donor)
        if userForm.is_valid() and donorForm.is_valid():
            userForm.save()
            donorForm.save()
            messages.success(request, 'Donor profile updated successfully.')
            return redirect('admin-donor')
    else:
        userForm = dforms.DonorUserUpdateForm(instance=user)
        donorForm = dforms.DonorForm(instance=donor)
    mydict = {'userForm': userForm, 'donorForm': donorForm}
    return render(request, 'blood/update_donor.html', context=mydict)


@login_required
def delete_donor_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    donor = dmodels.Donor.objects.get(id=pk)
    user = User.objects.get(id=donor.user_id)
    user.delete()
    donor.delete()
    return redirect('admin-donor')

@login_required
def admin_patient_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    patients = pmodels.Patient.objects.all()
    return render(request, 'blood/admin_patient.html', {'patients': patients})


@login_required
def update_patient_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    patient = pmodels.Patient.objects.get(id=pk)
    user = User.objects.get(id=patient.user_id)
    if request.method == 'POST':
        userForm = pforms.PatientUserUpdateForm(request.POST, instance=user)
        patientForm = pforms.PatientForm(request.POST, request.FILES, instance=patient)
        if userForm.is_valid() and patientForm.is_valid():
            userForm.save()
            patientForm.save()
            messages.success(request, 'Patient profile updated successfully.')
            return redirect('admin-patient')
    else:
        userForm = pforms.PatientUserUpdateForm(instance=user)
        patientForm = pforms.PatientForm(instance=patient)
    mydict = {'userForm': userForm, 'patientForm': patientForm}
    return render(request, 'blood/update_patient.html', context=mydict)


@login_required
def delete_patient_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    patient = pmodels.Patient.objects.get(id=pk)
    user = User.objects.get(id=patient.user_id)
    user.delete()
    patient.delete()
    return redirect('admin-patient')

@login_required
def admin_request_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    # Get all pending requests with proper ordering and patient info
    blood_requests = models.BloodRequest.objects.filter(status='Pending').select_related('patient', 'request_by_donor').order_by('-date')
    
    # Add summary statistics
    total_pending = blood_requests.count()
    
    # Calculate total units pending
    total_pending_units = blood_requests.aggregate(Sum('unit'))['unit__sum'] or 0
    
    context = {
        'blood_requests': blood_requests,  # Changed from 'requests' to 'blood_requests'
        'total_pending': total_pending,
        'total_pending_units': total_pending_units,
    }
    
    return render(request, 'blood/admin_request.html', context)

@login_required
def admin_request_history_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    # Get all processed requests (Approved or Rejected) with related data
    blood_requests = models.BloodRequest.objects.exclude(status='Pending').select_related('patient', 'request_by_donor').order_by('-date')
    
    # Calculate comprehensive statistics
    approved_count = blood_requests.filter(status='Approved').count()
    rejected_count = blood_requests.filter(status='Rejected').count()
    total_processed = blood_requests.count()
    
    # Calculate total units approved and rejected
    approved_units = blood_requests.filter(status='Approved').aggregate(Sum('unit'))
    total_approved_units = approved_units['unit__sum'] if approved_units['unit__sum'] else 0
    
    rejected_units = blood_requests.filter(status='Rejected').aggregate(Sum('unit'))
    total_rejected_units = rejected_units['unit__sum'] if rejected_units['unit__sum'] else 0
    
    # Calculate approval rate percentage
    approval_rate = 0
    if total_processed > 0:
        approval_rate = round((approved_count * 100) / total_processed, 1)
    
    # Get blood group wise statistics
    blood_group_stats = {}
    for blood_req in blood_requests:
        bg = blood_req.bloodgroup
        if bg not in blood_group_stats:
            blood_group_stats[bg] = {
                'approved': 0,
                'rejected': 0,
                'approved_units': 0,
                'rejected_units': 0
            }
        
        if blood_req.status == 'Approved':
            blood_group_stats[bg]['approved'] += 1
            blood_group_stats[bg]['approved_units'] += blood_req.unit
        else:
            blood_group_stats[bg]['rejected'] += 1
            blood_group_stats[bg]['rejected_units'] += blood_req.unit
    
    context = {
        'blood_requests': blood_requests,  # Changed from 'requests' to 'blood_requests'
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'total_processed': total_processed,
        'total_approved_units': total_approved_units,
        'total_rejected_units': total_rejected_units,
        'approval_rate': approval_rate,
        'blood_group_stats': blood_group_stats,
    }
    
    return render(request, 'blood/admin_request_history.html', context)

@login_required
def update_approve_status_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    try:
        blood_request = models.BloodRequest.objects.get(id=pk)
        
        # Check if already processed
        if blood_request.status != 'Pending':
            messages.warning(request, f'This request has already been {blood_request.status.lower()}.')
            return redirect('admin-request')
        
        # Get request details
        request_blood_group = blood_request.bloodgroup
        request_blood_unit = blood_request.unit
        patient_name = blood_request.patient_name
        
        try:
            # Check stock availability
            stock = models.Stock.objects.get(bloodgroup=request_blood_group)
            
            if stock.unit >= request_blood_unit:
                # Sufficient stock available - approve request
                stock.unit = stock.unit - request_blood_unit
                stock.save()
                
                blood_request.status = "Approved"
                blood_request.save()
                
                # Success message with details
                messages.success(
                    request, 
                    f'✅ Request Approved Successfully!\n'
                    f'Patient: {patient_name}\n'
                    f'Blood Group: {request_blood_group}\n'
                    f'Units Allocated: {request_blood_unit}ml\n'
                    f'Remaining Stock: {stock.unit}ml'
                )
                
                # Log the transaction for audit trail
                print(f"BLOOD REQUEST APPROVED - ID: {pk}, Patient: {patient_name}, "
                      f"Blood Group: {request_blood_group}, Units: {request_blood_unit}ml, "
                      f"Remaining Stock: {stock.unit}ml")
                      
            else:
                # Insufficient stock
                messages.error(
                    request, 
                    f'❌ Insufficient Stock!\n'
                    f'Requested: {request_blood_unit}ml of {request_blood_group}\n'
                    f'Available: {stock.unit}ml\n'
                    f'Shortage: {request_blood_unit - stock.unit}ml'
                )
                
                # Optionally auto-reject if no stock
                if stock.unit == 0:
                    blood_request.status = "Rejected"
                    blood_request.save()
                    messages.info(request, f'Request automatically rejected due to zero stock.')
                    
        except models.Stock.DoesNotExist:
            messages.error(request, f'❌ Error: Blood group {request_blood_group} not found in stock database.')
            
    except models.BloodRequest.DoesNotExist:
        messages.error(request, '❌ Error: Blood request not found.')
    except Exception as e:
        messages.error(request, f'❌ System Error: {str(e)}')
    
    return redirect('admin-request')

@login_required
def update_reject_status_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    try:
        blood_request = models.BloodRequest.objects.get(id=pk)
        
        # Check if already processed
        if blood_request.status != 'Pending':
            messages.warning(request, f'This request has already been {blood_request.status.lower()}.')
            return redirect('admin-request')
        
        # Get request details for logging
        patient_name = blood_request.patient_name
        request_blood_group = blood_request.bloodgroup
        request_blood_unit = blood_request.unit
        
        # Reject the request
        blood_request.status = "Rejected"
        blood_request.save()
        
        messages.success(
            request, 
            f'❌ Request Rejected Successfully!\n'
            f'Patient: {patient_name}\n'
            f'Blood Group: {request_blood_group}\n'
            f'Units Requested: {request_blood_unit}ml\n'
            f'No blood deducted from stock.'
        )
        
        # Log the transaction
        print(f"BLOOD REQUEST REJECTED - ID: {pk}, Patient: {patient_name}, "
              f"Blood Group: {request_blood_group}, Units: {request_blood_unit}ml")
              
    except models.BloodRequest.DoesNotExist:
        messages.error(request, '❌ Error: Blood request not found.')
    except Exception as e:
        messages.error(request, f'❌ System Error: {str(e)}')
    
    return redirect('admin-request')

# Enhanced donation approval functions
@login_required
def approve_donation_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    try:
        donation = dmodels.BloodDonate.objects.select_related('donor__user').get(id=pk)
        
        # Check if already processed
        if donation.status != 'Pending':
            messages.warning(request, f'This donation has already been {donation.status.lower()}.')
            return redirect('admin-donation')
        
        donation_blood_group = donation.bloodgroup
        donation_blood_unit = donation.unit
        donor_name = donation.donor.get_name

        try:
            stock = models.Stock.objects.get(bloodgroup=donation_blood_group)
            old_stock = stock.unit
            stock.unit = stock.unit + donation_blood_unit
            stock.save()

            donation.status = 'Approved'
            donation.save()
            
            messages.success(
                request, 
                f'✅ Donation Approved Successfully!\n'
                f'Donor: {donor_name}\n'
                f'Blood Group: {donation_blood_group}\n'
                f'Units Donated: {donation_blood_unit}ml\n'
                f'Previous Stock: {old_stock}ml\n'
                f'Updated Stock: {stock.unit}ml'
            )
            
            # Detailed logging
            print(f"BLOOD DONATION APPROVED - ID: {pk}, Donor: {donor_name}, "
                  f"Blood Group: {donation_blood_group}, Units: {donation_blood_unit}ml, "
                  f"Old Stock: {old_stock}ml, New Stock: {stock.unit}ml")
                  
        except models.Stock.DoesNotExist:
            messages.error(request, f'❌ Error: Blood group {donation_blood_group} not found in stock database.')
            print(f"ERROR: Stock not found for blood group {donation_blood_group}")
            
    except dmodels.BloodDonate.DoesNotExist:
        messages.error(request, '❌ Error: Donation record not found.')
        print(f"ERROR: BloodDonate with ID {pk} not found")
    except Exception as e:
        messages.error(request, f'❌ System Error: {str(e)}')
        print(f"ERROR in approve_donation_view: {str(e)}")
    
    return redirect('admin-donation')

@login_required
def reject_donation_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    try:
        donation = dmodels.BloodDonate.objects.select_related('donor__user').get(id=pk)
        
        # Check if already processed
        if donation.status != 'Pending':
            messages.warning(request, f'This donation has already been {donation.status.lower()}.')
            return redirect('admin-donation')
        
        donor_name = donation.donor.get_name
        donation_blood_group = donation.bloodgroup
        donation_blood_unit = donation.unit
        
        donation.status = 'Rejected'
        donation.save()
        
        messages.success(
            request, 
            f'❌ Donation Rejected Successfully!\n'
            f'Donor: {donor_name}\n'
            f'Blood Group: {donation_blood_group}\n'
            f'Units: {donation_blood_unit}ml\n'
            f'No blood added to stock.'
        )
        
        # Log the transaction
        print(f"BLOOD DONATION REJECTED - ID: {pk}, Donor: {donor_name}, "
              f"Blood Group: {donation_blood_group}, Units: {donation_blood_unit}ml")
              
    except dmodels.BloodDonate.DoesNotExist:
        messages.error(request, '❌ Error: Donation record not found.')
        print(f"ERROR: BloodDonate with ID {pk} not found")
    except Exception as e:
        messages.error(request, f'❌ System Error: {str(e)}')
        print(f"ERROR in reject_donation_view: {str(e)}")
    
    return redirect('admin-donation')

def request_blood_redirect_view(request):
    """Handle blood request redirect based on user status"""
    if request.user.is_authenticated:
        if request.user.groups.filter(name='PATIENT').exists():
            return redirect('make-request')
        elif request.user.groups.filter(name='DONOR').exists():
            return redirect('donor-request-blood')
        else:
            # For admin or other users, redirect to patient signup with parameter
            return redirect('/patient/patientsignup/?from_request=true')
    else:
        # For anonymous users, redirect to patient signup with parameter
        return redirect('/patient/patientsignup/?from_request=true')

@login_required
def admin_donation_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    
    # Get all donations with donor information, ordered by most recent first
    donations = dmodels.BloodDonate.objects.all().select_related('donor__user').order_by('-date')
    
    # Calculate comprehensive statistics
    total_donations = donations.count()
    pending_donations = donations.filter(status='Pending').count()
    approved_donations = donations.filter(status='Approved').count()
    rejected_donations = donations.filter(status='Rejected').count()
    
    # Calculate units statistics
    total_units_donated = donations.filter(status='Approved').aggregate(Sum('unit'))
    total_approved_units = total_units_donated['unit__sum'] if total_units_donated['unit__sum'] else 0
    
    pending_units = donations.filter(status='Pending').aggregate(Sum('unit'))
    total_pending_units = pending_units['unit__sum'] if pending_units['unit__sum'] else 0
    
    # Debug information
    print(f"ADMIN DONATION VIEW DEBUG:")
    print(f"Total donations found: {total_donations}")
    print(f"Pending: {pending_donations}, Approved: {approved_donations}, Rejected: {rejected_donations}")
    
    # Log recent donations for debugging
    for donation in donations[:5]:
        print(f"- ID: {donation.id}, Donor: {donation.donor.get_name}, "
              f"Blood Group: {donation.bloodgroup}, Units: {donation.unit}ml, "
              f"Status: {donation.status}, Date: {donation.date}")
    
    context = {
        'donations': donations,
        'total_donations': total_donations,
        'pending_donations': pending_donations,
        'approved_donations': approved_donations,
        'rejected_donations': rejected_donations,
        'total_approved_units': total_approved_units,
        'total_pending_units': total_pending_units,
    }
    
    return render(request, 'blood/admin_donation.html', context)


@login_required
def admin_analytics_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')

    today = timezone.now().date()
    range_param = request.GET.get('range', '30d')
    custom_start = request.GET.get('start_date')
    custom_end = request.GET.get('end_date')
    compare_mode = request.GET.get('compare', '')
    requested_panel = request.GET.get('panel', 'overview')
    allowed_panels = {'overview', 'operations', 'inventory', 'community'}
    active_panel = requested_panel if requested_panel in allowed_panels else 'overview'
    fallback_applied = False
    fallback_message = ''

    def parse_date(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    def format_label(start_value, end_value):
        return f"{start_value.strftime('%d %b %Y')} – {end_value.strftime('%d %b %Y')}"

    range_defaults = {
        '7d': 6,
        '30d': 29,
        '90d': 89,
        '365d': 364,
    }

    start_date = today - timedelta(days=range_defaults.get(range_param, 29))
    end_date = today

    if range_param == 'custom':
        parsed_start = parse_date(custom_start)
        parsed_end = parse_date(custom_end) or today
        if parsed_start:
            start_date = parsed_start
        if parsed_end:
            end_date = parsed_end

    if end_date > today:
        end_date = today

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    def scoped_querysets(window_start, window_end):
        return (
            models.BloodRequest.objects.filter(date__gte=window_start, date__lte=window_end),
            dmodels.BloodDonate.objects.filter(date__gte=window_start, date__lte=window_end),
        )

    requests_qs, donations_qs = scoped_querysets(start_date, end_date)

    if not requests_qs.exists() and not donations_qs.exists():
        earliest_request = models.BloodRequest.objects.order_by('date').values_list('date', flat=True).first()
        earliest_donation = dmodels.BloodDonate.objects.order_by('date').values_list('date', flat=True).first()
        latest_request = models.BloodRequest.objects.order_by('-date').values_list('date', flat=True).first()
        latest_donation = dmodels.BloodDonate.objects.order_by('-date').values_list('date', flat=True).first()

        available_starts = [d for d in [earliest_request, earliest_donation] if d]
        available_ends = [d for d in [latest_request, latest_donation] if d]

        if available_starts and available_ends:
            fallback_applied = True
            fallback_message = 'No activity in the selected window, expanded to cover the full historical range.'
            start_date = min(available_starts)
            end_date = max(available_ends)
            requests_qs, donations_qs = scoped_querysets(start_date, end_date)

    date_span = (end_date - start_date).days + 1
    date_range_label = format_label(start_date, end_date)

    approved_requests_qs = requests_qs.filter(status='Approved')
    approved_donations_qs = donations_qs.filter(status='Approved')

    request_units = requests_qs.aggregate(total=Sum('unit'))['total'] or 0
    approved_request_units = approved_requests_qs.aggregate(total=Sum('unit'))['total'] or 0
    donation_units = approved_donations_qs.aggregate(total=Sum('unit'))['total'] or 0

    summary_snapshot = {
        'requests_total': requests_qs.count(),
        'requests_approved': approved_requests_qs.count(),
        'requests_pending': requests_qs.filter(status='Pending').count(),
        'donations_total': donations_qs.count(),
        'donations_approved': approved_donations_qs.count(),
        'request_units': request_units,
        'approved_request_units': approved_request_units,
        'donation_units': donation_units,
    }

    conversion_rate = 0
    if summary_snapshot['requests_total']:
        conversion_rate = round((summary_snapshot['requests_approved'] * 100) / summary_snapshot['requests_total'], 1)

    summary_cards = [
        {
            'title': 'Requests Logged',
            'value': summary_snapshot['requests_total'],
            'subtitle': 'Submitted within window',
            'accent_class': 'accent-pink',
            'icon': 'fa-clipboard-list',
        },
        {
            'title': 'Requests Approved',
            'value': summary_snapshot['requests_approved'],
            'subtitle': f"{conversion_rate}% conversion",
            'accent_class': 'accent-green',
            'icon': 'fa-check-circle',
        },
        {
            'title': 'Units Allocated',
            'value': summary_snapshot['approved_request_units'],
            'subtitle': 'ml released to patients',
            'accent_class': 'accent-gold',
            'icon': 'fa-tint',
        },
        {
            'title': 'Units Donated',
            'value': summary_snapshot['donation_units'],
            'subtitle': 'Approved donations',
            'accent_class': 'accent-indigo',
            'icon': 'fa-hand-holding-heart',
        },
    ]

    # Comparison snapshot (previous equal window)
    comparison_rows = []
    compare_enabled = compare_mode == 'previous'
    if compare_enabled:
        compare_end = start_date - timedelta(days=1)
        compare_start = compare_end - timedelta(days=date_span - 1)
        prev_requests = models.BloodRequest.objects.filter(date__gte=compare_start, date__lte=compare_end)
        prev_donations = dmodels.BloodDonate.objects.filter(date__gte=compare_start, date__lte=compare_end)

        prev_snapshot = {
            'requests_total': prev_requests.count(),
            'requests_approved': prev_requests.filter(status='Approved').count(),
            'donations_total': prev_donations.count(),
            'donations_approved': prev_donations.filter(status='Approved').count(),
            'approved_request_units': prev_requests.filter(status='Approved').aggregate(total=Sum('unit'))['total'] or 0,
            'donation_units': prev_donations.filter(status='Approved').aggregate(total=Sum('unit'))['total'] or 0,
        }

        def build_compare_row(label, current_key, previous_key):
            current_value = summary_snapshot[current_key]
            previous_value = prev_snapshot.get(previous_key, 0)
            if previous_value == 0:
                delta = 100 if current_value else 0
            else:
                delta = round(((current_value - previous_value) / previous_value) * 100, 1)
            comparison_rows.append({
                'label': label,
                'current': current_value,
                'previous': previous_value,
                'delta': delta,
                'trend': 'up' if current_value >= previous_value else 'down',
            })

        build_compare_row('Requests Logged', 'requests_total', 'requests_total')
        build_compare_row('Requests Approved', 'requests_approved', 'requests_approved')
        build_compare_row('Donation Volume', 'donation_units', 'donation_units')

    # Timeline data (per-day units)
    requests_daily = requests_qs.values('date').order_by('date').annotate(units=Sum('unit'))
    donations_daily = approved_donations_qs.values('date').order_by('date').annotate(units=Sum('unit'))

    request_map = {entry['date']: float(entry['units'] or 0) for entry in requests_daily}
    donation_map = {entry['date']: float(entry['units'] or 0) for entry in donations_daily}
    approved_request_daily = approved_requests_qs.values('date').order_by('date').annotate(units=Sum('unit'))
    approved_request_map = {entry['date']: float(entry['units'] or 0) for entry in approved_request_daily}

    timeline_labels = []
    timeline_requests = []
    timeline_donations = []
    net_flow_values = []
    for offset in range(date_span):
        current_date = start_date + timedelta(days=offset)
        timeline_labels.append(current_date.strftime('%d %b'))
        timeline_requests.append(request_map.get(current_date, 0))
        timeline_donations.append(donation_map.get(current_date, 0))
        delta = donation_map.get(current_date, 0) - approved_request_map.get(current_date, 0)
        net_value = (net_flow_values[-1] if net_flow_values else 0) + delta
        net_flow_values.append(round(net_value, 2))

    timeline_payload = json.dumps(
        {
            'labels': timeline_labels,
            'requests': timeline_requests,
            'donations': timeline_donations,
        },
        cls=DjangoJSONEncoder,
    )

    net_flow_payload = json.dumps(
        {
            'labels': timeline_labels,
            'net': net_flow_values,
        },
        cls=DjangoJSONEncoder,
    )

    # Blood group distribution
    blood_groups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
    blood_group_requests = {bg: 0 for bg in blood_groups}
    blood_group_donations = {bg: 0 for bg in blood_groups}
    blood_group_stock = {bg: 0 for bg in blood_groups}

    for entry in requests_qs.values('bloodgroup').annotate(units=Sum('unit')):
        bg = entry['bloodgroup']
        if bg in blood_group_requests:
            blood_group_requests[bg] = float(entry['units'] or 0)

    for entry in approved_donations_qs.values('bloodgroup').annotate(units=Sum('unit')):
        bg = entry['bloodgroup']
        if bg in blood_group_donations:
            blood_group_donations[bg] = float(entry['units'] or 0)

    for stock in models.Stock.objects.filter(bloodgroup__in=blood_groups):
        blood_group_stock[stock.bloodgroup] = float(stock.unit)

    blood_group_payload = json.dumps(
        {
            'labels': blood_groups,
            'requests': [blood_group_requests[bg] for bg in blood_groups],
            'donations': [blood_group_donations[bg] for bg in blood_groups],
            'stock': [blood_group_stock[bg] for bg in blood_groups],
        },
        cls=DjangoJSONEncoder,
    )

    # Status breakdown data
    request_status_template = {status: 0 for status in ['Approved', 'Pending', 'Rejected']}
    donation_status_template = request_status_template.copy()

    for entry in requests_qs.values('status').annotate(total=Count('id')):
        status = entry['status']
        if status in request_status_template:
            request_status_template[status] = entry['total']

    for entry in donations_qs.values('status').annotate(total=Count('id')):
        status = entry['status']
        if status in donation_status_template:
            donation_status_template[status] = entry['total']

    status_payload = json.dumps(
        {
            'labels': list(request_status_template.keys()),
            'requests': list(request_status_template.values()),
            'donations': list(donation_status_template.values()),
        },
        cls=DjangoJSONEncoder,
    )

    daily_status_entries = requests_qs.values('date', 'status').annotate(total=Count('id'))
    status_labels = ['Approved', 'Pending', 'Rejected']
    status_timeline_map = {
        label: [0 for _ in range(date_span)] for label in status_labels
    }
    day_index_lookup = {
        (start_date + timedelta(days=i)): i for i in range(date_span)
    }
    for entry in daily_status_entries:
        entry_date = entry['date']
        idx = day_index_lookup.get(entry_date)
        if idx is None:
            continue
        status = entry['status']
        if status in status_timeline_map:
            status_timeline_map[status][idx] = entry['total']

    status_timeline_payload = json.dumps(
        {
            'labels': timeline_labels,
            'series': status_timeline_map,
        },
        cls=DjangoJSONEncoder,
    )

    # Request channel breakdown (patient vs donor vs quick)
    channel_totals = OrderedDict({
        'Patient Portal': {'count': 0, 'units': 0},
        'Donor Self-Serve': {'count': 0, 'units': 0},
        'Quick Request': {'count': 0, 'units': 0},
    })
    for req in requests_qs.select_related('patient__user', 'request_by_donor__user'):
        if req.patient_id:
            key = 'Patient Portal'
        elif req.request_by_donor_id:
            key = 'Donor Self-Serve'
        else:
            key = 'Quick Request'
        channel_totals[key]['count'] += 1
        channel_totals[key]['units'] += float(req.unit or 0)

    channel_mix_payload = json.dumps(
        {
            'labels': list(channel_totals.keys()),
            'counts': [values['count'] for values in channel_totals.values()],
            'units': [values['units'] for values in channel_totals.values()],
        },
        cls=DjangoJSONEncoder,
    )

    # Monthly summary (grouped by trunc month)
    monthly_dict = OrderedDict()
    request_months = requests_qs.annotate(month=TruncMonth('date')).values('month').annotate(
        count=Count('id'), units=Sum('unit')
    )
    donation_months = approved_donations_qs.annotate(month=TruncMonth('date')).values('month').annotate(
        count=Count('id'), units=Sum('unit')
    )
    for entry in request_months:
        month = entry['month']
        if not month:
            continue
        monthly_dict.setdefault(month, {'requests': {'count': 0, 'units': 0}, 'donations': {'count': 0, 'units': 0}})
        monthly_dict[month]['requests']['count'] = entry['count']
        monthly_dict[month]['requests']['units'] = float(entry['units'] or 0)
    for entry in donation_months:
        month = entry['month']
        if not month:
            continue
        monthly_dict.setdefault(month, {'requests': {'count': 0, 'units': 0}, 'donations': {'count': 0, 'units': 0}})
        monthly_dict[month]['donations']['count'] = entry['count']
        monthly_dict[month]['donations']['units'] = float(entry['units'] or 0)

    sorted_months = sorted(monthly_dict.keys())[-6:]
    monthly_summary_payload = json.dumps(
        {
            'labels': [month.strftime('%b %Y') for month in sorted_months],
            'request_counts': [monthly_dict[month]['requests']['count'] for month in sorted_months],
            'donation_counts': [monthly_dict[month]['donations']['count'] for month in sorted_months],
            'request_units': [monthly_dict[month]['requests']['units'] for month in sorted_months],
            'donation_units': [monthly_dict[month]['donations']['units'] for month in sorted_months],
        },
        cls=DjangoJSONEncoder,
    )

    # Top performers (requesters + donors)
    requester_totals = defaultdict(float)
    for req in requests_qs.select_related('patient__user', 'request_by_donor__user'):
        role = 'Quick'
        name = req.patient_name or 'Anonymous'
        if req.patient and req.patient.user:
            role = 'Patient'
            name = req.patient.get_name
        elif req.request_by_donor and req.request_by_donor.user:
            role = 'Donor'
            name = req.request_by_donor.get_name
        requester_totals[f"{role} · {name}"] += float(req.unit or 0)

    top_requesters = sorted(
        [{'name': key, 'units': value} for key, value in requester_totals.items()],
        key=lambda item: item['units'],
        reverse=True,
    )[:5]

    donor_leader_entries = (
        approved_donations_qs
        .values('donor_id')
        .annotate(
            total_units=Sum('unit'),
            donation_count=Count('id'),
            last_donation=Max('date'),
        )
        .order_by('-total_units')[:5]
    )
    donor_map = dmodels.Donor.objects.select_related('user').in_bulk([entry['donor_id'] for entry in donor_leader_entries])
    placeholder_avatar = static('image/homepage.png')

    top_donors = []
    top_donor_cards = []
    for rank, entry in enumerate(donor_leader_entries, start=1):
        donor = donor_map.get(entry['donor_id'])
        if not donor:
            continue
        full_name = donor.get_name
        total_units_value = float(entry['total_units'] or 0)
        top_donors.append({
            'name': full_name,
            'units': total_units_value,
        })
        top_donor_cards.append({
            'rank': rank,
            'name': full_name,
            'bloodgroup': donor.bloodgroup,
            'units': total_units_value,
            'donation_count': entry['donation_count'] or 0,
            'last_donation': entry['last_donation'],
            'profile_pic_url': donor.profile_pic.url if donor.has_profile_pic else placeholder_avatar,
        })

    top_requesters_payload = json.dumps(top_requesters, cls=DjangoJSONEncoder)

    context = {
        'date_range_label': date_range_label,
        'range_param': range_param,
        'start_date_value': start_date.strftime('%Y-%m-%d'),
        'end_date_value': end_date.strftime('%Y-%m-%d'),
        'summary_cards': summary_cards,
        'timeline_data': timeline_payload,
    'net_flow_data': net_flow_payload,
        'blood_group_data': blood_group_payload,
        'status_data': status_payload,
    'status_timeline_data': status_timeline_payload,
    'channel_mix_data': channel_mix_payload,
    'monthly_summary_data': monthly_summary_payload,
    'top_requesters_data': top_requesters_payload,
    'top_donor_cards': top_donor_cards,
        'comparison_rows': comparison_rows,
        'compare_enabled': compare_enabled,
        'conversion_rate': conversion_rate,
        'fallback_applied': fallback_applied,
        'fallback_message': fallback_message,
        'active_panel': active_panel,
    }

    return render(request, 'blood/admin_analytics.html', context)


@login_required
def admin_leadership_view(request):
    if not request.user.is_superuser:
        return redirect('adminlogin')

    placeholder_avatar = static('image/homepage.png')

    donor_stats_qs = dmodels.Donor.objects.select_related('user').annotate(
        total_units=Sum('blooddonate__unit', filter=Q(blooddonate__status='Approved')),
        donations_count=Count('blooddonate', filter=Q(blooddonate__status='Approved')),
        last_donation=Max('blooddonate__date', filter=Q(blooddonate__status='Approved')),
    ).order_by('-total_units', '-donations_count', 'user__first_name')

    donor_leaderboard = []
    for idx, donor in enumerate(donor_stats_qs, start=1):
        try:
            pic = donor.profile_pic.url if donor.profile_pic and hasattr(donor.profile_pic, 'url') else placeholder_avatar
        except Exception:
            pic = placeholder_avatar
        donor_leaderboard.append({
            'rank': idx,
            'id': donor.id,
            'name': donor.get_name,
            'username': donor.user.username,
            'profile_pic': pic,
            'bloodgroup': donor.bloodgroup,
            'total_units': float(donor.total_units or 0),
            'donations_count': int(donor.donations_count or 0),
            'last_donation': donor.last_donation,
        })

    leaderboard_totals = {
        'members': len(donor_leaderboard),
        'units': round(sum(entry['total_units'] for entry in donor_leaderboard), 2) if donor_leaderboard else 0,
        'donations': sum(entry['donations_count'] for entry in donor_leaderboard) if donor_leaderboard else 0,
    }
    leaderboard_top_three = donor_leaderboard[:3]
    leaderboard_rest = donor_leaderboard[3:]

    approved_donations = dmodels.BloodDonate.objects.filter(status='Approved').select_related('donor__user').order_by('-date')
    recent_activity = []
    for donation in approved_donations[:6]:
        try:
            donor_pic = donation.donor.profile_pic.url if donation.donor.profile_pic and hasattr(donation.donor.profile_pic, 'url') else placeholder_avatar
        except Exception:
            donor_pic = placeholder_avatar
        recent_activity.append({
            'name': donation.donor.get_name,
            'bloodgroup': donation.bloodgroup,
            'units': donation.unit,
            'date': donation.date,
            'profile_pic': donor_pic,
        })

    blood_group_totals = []
    for entry in approved_donations.values('bloodgroup').annotate(units=Sum('unit')).order_by('-units'):
        blood_group_totals.append({
            'bloodgroup': entry['bloodgroup'],
            'units': float(entry['units'] or 0),
        })

    context = {
        'leaderboard_totals': leaderboard_totals,
        'leaderboard_top_three': leaderboard_top_three,
        'leaderboard_rest': leaderboard_rest,
        'donor_leaderboard': donor_leaderboard,
        'recent_activity': recent_activity,
        'blood_group_totals': blood_group_totals,
        'has_leaderboard': bool(donor_leaderboard),
    }

    return render(request, 'blood/admin_leadership.html', context)


def test_sms(request):
    """Manual endpoint to verify AWS SNS connectivity."""

    phone = request.GET.get('phone', '+91XXXXXXXXXX')
    message = "Hello from BloodBridge! SMS working successfully."
    result = send_sms(phone, message)
    status_code = 200 if result.get('status') == 'success' else 500
    return JsonResponse(result, status=status_code)

def quick_request_view(request):
    """Allow anonymous users to make quick blood requests"""
    context = {}
    if request.method == 'POST':
        # Get form data
        patient_name = request.POST.get('patient_name', '').strip()
        patient_age_raw = request.POST.get('patient_age', '').strip()
        reason = request.POST.get('reason', '').strip()
        bloodgroup = request.POST.get('bloodgroup', '').strip()
        unit_raw = request.POST.get('unit', '').strip()
        request_zipcode = request.POST.get('request_zipcode', '').strip()
        contact_number = request.POST.get('contact_number', '').strip()
        emergency_contact = request.POST.get('emergency_contact', '').strip()

        context = {
            'patient_name': patient_name,
            'patient_age': patient_age_raw,
            'reason': reason,
            'bloodgroup': bloodgroup,
            'unit': unit_raw,
            'contact_number': contact_number,
            'emergency_contact': emergency_contact,
            'request_zipcode': request_zipcode,
        }

        # Enhanced validation
        errors = []
        patient_age = None
        unit = None
        
        if not patient_name:
            errors.append('Patient name is required.')
        elif len(patient_name) < 2:
            errors.append('Patient name must be at least 2 characters.')
        
        if not patient_age_raw:
            errors.append('Patient age is required.')
        else:
            try:
                patient_age = int(patient_age_raw)
                if patient_age < 1 or patient_age > 120:
                    errors.append('Patient age must be between 1 and 120.')
            except ValueError:
                errors.append('Please enter a valid age.')
        
        if not reason:
            errors.append('Reason for blood request is required.')
        elif len(reason) < 10:
            errors.append('Please provide a detailed reason (at least 10 characters).')
        
        if not bloodgroup:
            errors.append('Blood group is required.')
        elif bloodgroup not in ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']:
            errors.append('Please select a valid blood group.')
        
        if not unit_raw:
            errors.append('Unit amount is required.')
        else:
            try:
                unit = int(unit_raw)
                if unit < 100 or unit > 500:
                    errors.append('Unit amount must be between 100ml and 500ml.')
            except ValueError:
                errors.append('Please enter a valid unit amount.')
        
        if not contact_number:
            errors.append('Contact number is required.')
        elif len(contact_number) < 10:
            errors.append('Please provide a valid contact number.')

        if not request_zipcode:
            errors.append('Zip/Postal code is required so volunteers know where to route units.')
        elif not request_zipcode.isdigit() or not (4 <= len(request_zipcode) <= 10):
            errors.append('Please enter a valid zip/postal code (4-10 digits).')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'blood/quick_request.html', context)
        
        # Create blood request with enhanced reason including contact info
        enhanced_reason = f"{reason}\n\nContact: {contact_number}"
        if emergency_contact:
            enhanced_reason += f"\nEmergency Contact: {emergency_contact}"
        
        try:
            # Create the blood request without patient association
            blood_request = models.BloodRequest.objects.create(
                patient=None,  # No patient account
                request_by_donor=None,  # No donor account
                patient_name=patient_name,
                patient_age=patient_age,
                reason=enhanced_reason,
                bloodgroup=bloodgroup,
                unit=unit,
                status='Pending',
                is_urgent=True,
                request_zipcode=request_zipcode,
            )
            
            messages.success(
                request, 
                f'🩸 Emergency Blood Request Submitted Successfully!\n\n'
                f'Request ID: #{blood_request.id}\n'
                f'Patient: {patient_name}\n'
                f'Blood Group: {bloodgroup}\n'
                f'Units: {unit}ml\n\n'
                f'⚡ This is a priority request that will be reviewed immediately.\n'
                f'Our coordinators will reach out at {contact_number} with next steps.\n\n'
                f'Please keep this Request ID for reference: #{blood_request.id}'
            )
            
            # Log the quick request for admin monitoring
            print(
                f"QUICK REQUEST SUBMITTED - ID: {blood_request.id}, "
                f"Patient: {patient_name}, Blood Group: {bloodgroup}, "
                f"Units: {unit}ml, Contact: {contact_number}"
            )

            try:
                sms_service.notify_matched_donors(blood_request, contact_number=contact_number)
            except Exception as alert_error:  # pragma: no cover - logging fallback only
                logger.error(
                    "Failed to dispatch SNS alert for quick request %s: %s",
                    blood_request.id,
                    alert_error,
                )
            else:
                sms_service.send_requester_confirmation(blood_request, contact_number)
            
            # Redirect to success page with request ID
            return redirect('quick-request-success', request_id=blood_request.id)
            
        except Exception as e:
            print(f"Error creating quick blood request: {str(e)}")
            messages.error(request, f'Error submitting request: {str(e)}')
    
    return render(request, 'blood/quick_request.html', context)

def quick_request_success_view(request, request_id):
    """Display success page for quick requests"""
    try:
        blood_request = models.BloodRequest.objects.get(id=request_id)
        context = {
            'blood_request': blood_request,
            'request_id': request_id,
        }
        return render(request, 'blood/quick_request_success.html', context)
    except models.BloodRequest.DoesNotExist:
        messages.error(request, 'Request not found.')
        return redirect('quick-request')


def knowledge_chatbot_view(request):
    """Guided FAQ chatbot with contextual stats and quick prompts."""
    project_stats = {
        'donors': dmodels.Donor.objects.count(),
        'patients': pmodels.Patient.objects.count(),
        'donations': dmodels.BloodDonate.objects.count(),
        'pending_requests': models.BloodRequest.objects.filter(status='Pending').count(),
        'stock_units': models.Stock.objects.aggregate(total_units=Sum('unit')).get('total_units') or 0,
    }

    latest_requests = (
        models.BloodRequest.objects.select_related('patient__user', 'request_by_donor__user')
        .order_by('-date')[:5]
    )
    request_timeline = []
    for entry in latest_requests:
        if entry.patient:
            actor = entry.patient.get_name
            role = 'Patient'
        elif entry.request_by_donor:
            actor = entry.request_by_donor.get_name
            role = 'Donor'
        else:
            actor = entry.patient_name
            role = 'Guest'

        request_timeline.append({
            'id': entry.id,
            'actor': actor,
            'role': role,
            'bloodgroup': entry.bloodgroup,
            'unit': entry.unit,
            'status': entry.status,
            'date': entry.date,
        })

    faq_sections = deepcopy(CHATBOT_FAQ)
    prompt_list = list(CHATBOT_PROMPTS)

    context = {
        'faq_sections': faq_sections,
        'chatbot_prompts': prompt_list,
        'project_stats': project_stats,
        'request_timeline': request_timeline,
        'faq_json': json.dumps(faq_sections, cls=DjangoJSONEncoder),
        'prompts_json': json.dumps(prompt_list, cls=DjangoJSONEncoder),
    }
    return render(request, 'blood/chatbot.html', context)
