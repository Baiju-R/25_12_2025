import logging

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.contrib import messages
from django.db.models import Sum

from blood.services import sms as sms_service
from .forms import DonorUserForm, DonorForm
from .models import Donor, BloodDonate

logger = logging.getLogger(__name__)

def donorsignup_view(request):
    userForm = DonorUserForm()
    donorForm = DonorForm()
    mydict = {'userForm': userForm, 'donorForm': donorForm}
    
    if request.method == 'POST':
        userForm = DonorUserForm(request.POST)
        donorForm = DonorForm(request.POST, request.FILES)
        
        print("POST Data:", request.POST)
        print("User Form Valid:", userForm.is_valid())
        print("Donor Form Valid:", donorForm.is_valid())
        
        if userForm.errors:
            print("User Form Errors:", userForm.errors)
        if donorForm.errors:
            print("Donor Form Errors:", donorForm.errors)
        
        if userForm.is_valid() and donorForm.is_valid():
            try:
                # Create user
                user = userForm.save(commit=False)
                user.set_password(user.password)
                user.save()
                
                # Create donor
                donor = donorForm.save(commit=False)
                donor.user = user
                donor.save()
                
                # Add to donor group
                my_donor_group, created = Group.objects.get_or_create(name='DONOR')
                my_donor_group.user_set.add(user)
                
                messages.success(request, 'Donor account created successfully! You can now login.')
                return redirect('donorlogin')
                
            except Exception as e:
                print("Error during donor signup:", str(e))
                messages.error(request, f'Error creating account: {str(e)}')
        else:
            # Form validation failed
            error_messages = []
            
            # Collect user form errors
            for field, errors in userForm.errors.items():
                for error in errors:
                    error_messages.append(f"{field.replace('_', ' ').title()}: {error}")
            
            # Collect donor form errors
            for field, errors in donorForm.errors.items():
                for error in errors:
                    error_messages.append(f"{field.replace('_', ' ').title()}: {error}")
            
            for error in error_messages:
                messages.error(request, error)
    
    return render(request, 'donor/donorsignup.html', context=mydict)

def donorlogin_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        print(f"Donor login attempt - Username: {username}")
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            print(f"User authenticated: {user.username}")
            print(f"User groups: {[g.name for g in user.groups.all()]}")
            
            if user.groups.filter(name='DONOR').exists():
                login(request, user)
                messages.success(request, f'Welcome back, {user.first_name}!')
                return redirect('donor-dashboard')
            else:
                messages.error(request, 'This account is not registered as a donor.')
        else:
            print("Authentication failed")
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'donor/donorlogin.html')

@login_required
def donor_dashboard_view(request):
    print(f"DEBUG: Donor dashboard accessed by user: {request.user.username}")
    print(f"DEBUG: User is authenticated: {request.user.is_authenticated}")
    print(f"DEBUG: User groups: {[g.name for g in request.user.groups.all()]}")
    
    if not request.user.groups.filter(name='DONOR').exists():
        print("DEBUG: User not in DONOR group, redirecting to login")
        messages.error(request, 'Access denied. Donor account required.')
        return redirect('donorlogin')
    
    try:
        donor = Donor.objects.get(user=request.user)
        print(f"DEBUG: Donor profile found: {donor.get_name}")
        
        # Add comprehensive debugging
        donations = BloodDonate.objects.filter(donor=donor)
        print(f"DEBUG: Found {donations.count()} donations for donor")
        
        # Get donation statistics
        total_donations = donations.count()
        approved_donations = donations.filter(status='Approved').count()
        pending_donations = donations.filter(status='Pending').count()
        rejected_donations = donations.filter(status='Rejected').count()
        
        # Calculate total units donated (approved only)
        approved_units = donations.filter(status='Approved').aggregate(Sum('unit'))
        total_units_donated = approved_units['unit__sum'] if approved_units['unit__sum'] else 0
        
        # Get blood requests made by this donor
        from blood.models import BloodRequest
        blood_requests = BloodRequest.objects.filter(request_by_donor=donor)
        requestmade = blood_requests.count()
        request_pending = blood_requests.filter(status='Pending').count()
        request_approved = blood_requests.filter(status='Approved').count()
        request_rejected = blood_requests.filter(status='Rejected').count()
        
        # Get recent activities
        recent_donations = donations.order_by('-date')[:5]
        recent_requests = blood_requests.order_by('-date')[:5]
        
        print(f"DEBUG: Donor statistics: Donations={total_donations}, Requests={requestmade}")
        
        context = {
            'donor': donor,
            'total_donations': total_donations,
            'approved_donations': approved_donations,
            'pending_donations': pending_donations,
            'rejected_donations': rejected_donations,
            'total_units_donated': total_units_donated,
            'recent_donations': recent_donations,
            'requestmade': requestmade,
            'request_pending': request_pending,
            'request_approved': request_approved,
            'request_rejected': request_rejected,
            'recent_requests': recent_requests,
        }
        
    except Donor.DoesNotExist:
        print(f"DEBUG: Donor profile not found for user: {request.user.username}")
        messages.error(request, 'Donor profile not found. Please contact support.')
        context = {
            'donor': None,
            'total_donations': 0,
            'approved_donations': 0,
            'pending_donations': 0,
            'rejected_donations': 0,
            'total_units_donated': 0,
            'requestmade': 0,
            'request_pending': 0,
            'request_approved': 0,
            'request_rejected': 0,
            'recent_donations': [],
            'recent_requests': [],
        }
    except Exception as e:
        print(f"Error in donor dashboard: {str(e)}")
        messages.error(request, f'Dashboard error: {str(e)}')
        context = {
            'donor': None,
            'total_donations': 0,
            'approved_donations': 0,
            'pending_donations': 0,
            'rejected_donations': 0,
            'total_units_donated': 0,
            'requestmade': 0,
            'request_pending': 0,
            'request_approved': 0,
            'request_rejected': 0,
            'recent_donations': [],
            'recent_requests': [],
        }
    
    print(f"DEBUG: Rendering template with context keys: {list(context.keys())}")
    return render(request, 'donor/donor_dashboard.html', context)

@login_required
def donate_blood_view(request):
    if not request.user.groups.filter(name='DONOR').exists():
        messages.error(request, 'Access denied. Donor account required.')
        return redirect('donorlogin')
    
    try:
        donor = Donor.objects.get(user=request.user)
    except Donor.DoesNotExist:
        messages.error(request, 'Donor profile not found. Please contact support.')
        return redirect('donor-dashboard')
    
    if request.method == 'POST':
        bloodgroup = request.POST.get('bloodgroup', '').strip()
        unit = request.POST.get('unit', '').strip()
        disease = request.POST.get('disease', 'None').strip()
        age = request.POST.get('age', '').strip()
        
        # Enhanced validation
        errors = []
        
        if not bloodgroup or bloodgroup == 'Choose Blood Group':
            errors.append('Please select your blood group.')
        
        if not unit:
            errors.append('Unit amount is required.')
        else:
            try:
                unit_val = int(unit)
                if unit_val < 100 or unit_val > 500:
                    errors.append('Unit amount must be between 100ml and 500ml.')
            except ValueError:
                errors.append('Please enter a valid unit amount.')
        
        if not age:
            errors.append('Age is required.')
        else:
            try:
                age_val = int(age)
                if age_val < 18 or age_val > 65:
                    errors.append('Age must be between 18 and 65 years for blood donation.')
            except ValueError:
                errors.append('Please enter a valid age.')
        
        if not disease:
            disease = 'None'
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'donor/donate_blood.html', {'donor': donor})
        
        try:
            BloodDonate.objects.create(
                donor=donor,
                disease=disease,
                age=int(age),
                bloodgroup=bloodgroup,
                unit=int(unit),
                status='Pending'
            )
            
            messages.success(request, f'Donation request submitted successfully! {unit}ml of {bloodgroup} blood donation pending approval.')
            return redirect('donor-history')
            
        except Exception as e:
            print(f"Error creating blood donation: {str(e)}")
            messages.error(request, f'Error submitting donation: {str(e)}')
    
    return render(request, 'donor/donate_blood.html', {'donor': donor})

@login_required
def donor_history_view(request):
    if not request.user.groups.filter(name='DONOR').exists():
        messages.error(request, 'Access denied. Donor account required.')
        return redirect('donorlogin')
    
    try:
        donor = Donor.objects.get(user=request.user)
        donations = BloodDonate.objects.filter(donor=donor).order_by('-date')
        
        # Calculate statistics
        total_donations = donations.count()
        approved_count = donations.filter(status='Approved').count()
        pending_count = donations.filter(status='Pending').count()
        rejected_count = donations.filter(status='Rejected').count()
        
        # Calculate total units (approved only)
        approved_units = donations.filter(status='Approved').aggregate(Sum('unit'))
        total_approved_units = approved_units['unit__sum'] if approved_units['unit__sum'] else 0
        
        context = {
            'donations': donations,
            'total_donations': total_donations,
            'approved_count': approved_count,
            'pending_count': pending_count,
            'rejected_count': rejected_count,
            'total_approved_units': total_approved_units,
        }
    except Donor.DoesNotExist:
        messages.error(request, 'Donor profile not found. Please contact support.')
        context = {
            'donations': [],
            'total_donations': 0,
            'approved_count': 0,
            'pending_count': 0,
            'rejected_count': 0,
            'total_approved_units': 0,
        }
    
    return render(request, 'donor/donation_history.html', context)

@login_required
def donor_request_blood_view(request):
    if not request.user.groups.filter(name='DONOR').exists():
        messages.error(request, 'Access denied. Donor account required.')
        return redirect('donorlogin')
    
    try:
        donor = Donor.objects.get(user=request.user)
    except Donor.DoesNotExist:
        messages.error(request, 'Donor profile not found. Please contact support.')
        return redirect('donor-dashboard')
    
    form_data = {
        'patient_name': '',
        'patient_age': '',
        'reason': '',
        'bloodgroup': '',
        'unit': '',
        'request_zipcode': donor.zipcode or '',
        'is_urgent': False,
    }
    
    if request.method == 'POST':
        from blood.models import BloodRequest
        
        form_data.update({
            'patient_name': request.POST.get('patient_name', '').strip(),
            'patient_age': request.POST.get('patient_age', '').strip(),
            'reason': request.POST.get('reason', '').strip(),
            'bloodgroup': request.POST.get('bloodgroup', '').strip(),
            'unit': request.POST.get('unit', '').strip(),
            'request_zipcode': request.POST.get('request_zipcode', '').strip(),
            'is_urgent': request.POST.get('is_urgent') == 'on',
        })
        patient_name = form_data['patient_name']
        patient_age_raw = form_data['patient_age']
        reason = form_data['reason']
        bloodgroup = form_data['bloodgroup']
        unit_raw = form_data['unit']
        request_zipcode = form_data['request_zipcode']
        is_urgent = form_data['is_urgent']
        
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
        
        if not bloodgroup or bloodgroup == 'Choose Blood Group':
            errors.append('Please select a blood group.')
        
        if not unit_raw:
            errors.append('Unit amount is required.')
        else:
            try:
                unit = int(unit_raw)
                if unit < 100 or unit > 500:
                    errors.append('Unit amount must be between 100ml and 500ml.')
            except ValueError:
                errors.append('Please enter a valid unit amount.')

        if request_zipcode:
            if not request_zipcode.isdigit() or not (4 <= len(request_zipcode) <= 10):
                errors.append('Zip/Postal code must be 4-10 digits.')
        elif is_urgent:
            errors.append('Zip/Postal code is required so admins can triage urgent requests locally.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'donor/makerequest.html', {'donor': donor, 'form_data': form_data})
        
        try:
            blood_request = BloodRequest.objects.create(
                request_by_donor=donor,
                patient_name=patient_name,
                patient_age=patient_age,
                reason=reason,
                bloodgroup=bloodgroup,
                unit=unit,
                status='Pending',
                is_urgent=is_urgent,
                request_zipcode=request_zipcode,
            )
            
            success_msg = (
                f'Blood request submitted successfully! Requested {unit}ml of {bloodgroup} blood for {patient_name}.'
            )
            if is_urgent:
                success_msg += ' Admins will prioritize this request and coordinate follow-ups directly.'
            messages.success(request, success_msg)

            if is_urgent:
                try:
                    sms_service.notify_matched_donors(blood_request, contact_number=donor.mobile)
                except Exception as alert_error:  # pragma: no cover - defensive logging only
                    logger.error(
                        "Failed to dispatch SNS alert for donor request %s: %s",
                        blood_request.id,
                        alert_error,
                    )
                sms_service.send_requester_confirmation(blood_request, donor.mobile)
            return redirect('donor-request-history')
            
        except Exception as e:
            print(f"Error creating blood request: {str(e)}")
            messages.error(request, f'Error submitting request: {str(e)}')
    
    return render(request, 'donor/makerequest.html', {'donor': donor, 'form_data': form_data})

@login_required
def donor_request_history_view(request):
    if not request.user.groups.filter(name='DONOR').exists():
        messages.error(request, 'Access denied. Donor account required.')
        return redirect('donorlogin')
    
    try:
        donor = Donor.objects.get(user=request.user)
        from blood.models import BloodRequest
        requests = BloodRequest.objects.filter(request_by_donor=donor).order_by('-date')
        
        # Calculate statistics
        total_requests = requests.count()
        approved_count = requests.filter(status='Approved').count()
        pending_count = requests.filter(status='Pending').count()
        rejected_count = requests.filter(status='Rejected').count()
        
        context = {
            'requests': requests,
            'total_requests': total_requests,
            'approved_count': approved_count,
            'pending_count': pending_count,
            'rejected_count': rejected_count,
        }
    except Donor.DoesNotExist:
        messages.error(request, 'Donor profile not found. Please contact support.')
        context = {
            'requests': [],
            'total_requests': 0,
            'approved_count': 0,
            'pending_count': 0,
            'rejected_count': 0,
        }
    
    return render(request, 'donor/request_history.html', context)
