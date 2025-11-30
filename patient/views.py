from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.contrib import messages
from .forms import PatientUserForm, PatientForm
from .models import Patient
from blood.models import BloodRequest
from django.db.models import Sum

def patientsignup_view(request):
    userForm = PatientUserForm()
    patientForm = PatientForm()
    mydict = {'userForm': userForm, 'patientForm': patientForm}
    
    # Check if coming from request-blood redirect
    from_request = request.GET.get('from_request', False)
    
    if request.method == 'POST':
        userForm = PatientUserForm(request.POST)
        patientForm = PatientForm(request.POST, request.FILES)
        
        # Debug form data
        print("POST Data:", request.POST)
        print("User Form Valid:", userForm.is_valid())
        print("Patient Form Valid:", patientForm.is_valid())
        
        if userForm.errors:
            print("User Form Errors:", userForm.errors)
        if patientForm.errors:
            print("Patient Form Errors:", patientForm.errors)
        
        if userForm.is_valid() and patientForm.is_valid():
            try:
                # Create user
                user = userForm.save(commit=False)
                user.set_password(user.password)
                user.save()
                
                # Create patient
                patient = patientForm.save(commit=False)
                patient.user = user
                patient.save()
                
                # Add to patient group
                my_patient_group, created = Group.objects.get_or_create(name='PATIENT')
                my_patient_group.user_set.add(user)
                
                messages.success(request, 'Account created successfully! You can now login.')
                
                # If coming from request blood, redirect to make request after signup
                if from_request:
                    # Auto login the user and redirect to make request
                    login(request, user)
                    messages.info(request, 'Welcome! You can now make your blood request.')
                    return redirect('make-request')
                else:
                    return redirect('patientlogin')
                    
            except Exception as e:
                print("Error during signup:", str(e))
                messages.error(request, f'Error creating account: {str(e)}')
        else:
            # Form validation failed
            error_messages = []
            
            # Collect user form errors
            for field, errors in userForm.errors.items():
                for error in errors:
                    error_messages.append(f"{field.replace('_', ' ').title()}: {error}")
            
            # Collect patient form errors
            for field, errors in patientForm.errors.items():
                for error in errors:
                    error_messages.append(f"{field.replace('_', ' ').title()}: {error}")
            
            for error in error_messages:
                messages.error(request, error)
    
    mydict['from_request'] = from_request
    return render(request, 'patient/patientsignup.html', context=mydict)

def patientlogin_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        print(f"Login attempt - Username: {username}")
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            print(f"User authenticated: {user.username}")
            print(f"User groups: {[g.name for g in user.groups.all()]}")
            
            if user.groups.filter(name='PATIENT').exists():
                login(request, user)
                messages.success(request, f'Welcome back, {user.first_name}!')
                return redirect('patient-dashboard')
            else:
                messages.error(request, 'This account is not registered as a patient.')
        else:
            print("Authentication failed")
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'patient/patientlogin.html')

@login_required
def patient_dashboard_view(request):
    if not request.user.groups.filter(name='PATIENT').exists():
        messages.error(request, 'Access denied. Patient account required.')
        return redirect('patientlogin')
    
    try:
        patient = Patient.objects.get(user=request.user)
        requests = BloodRequest.objects.filter(patient=patient)
        
        # Calculate detailed statistics
        total_requests = requests.count()
        approved_requests = requests.filter(status='Approved').count()
        pending_requests = requests.filter(status='Pending').count()
        rejected_requests = requests.filter(status='Rejected').count()
        
        # Calculate total units requested and approved
        total_units_requested = requests.aggregate(Sum('unit'))
        total_units_requested = total_units_requested['unit__sum'] if total_units_requested['unit__sum'] else 0
        
        approved_units = requests.filter(status='Approved').aggregate(Sum('unit'))
        total_approved_units = approved_units['unit__sum'] if approved_units['unit__sum'] else 0
        
        # Get recent requests
        recent_requests = requests.order_by('-date')[:5]
        
        context = {
            'patient': patient,
            'total_requests': total_requests,
            'approved_requests': approved_requests,
            'pending_requests': pending_requests,
            'rejected_requests': rejected_requests,
            'total_units_requested': total_units_requested,
            'total_approved_units': total_approved_units,
            'recent_requests': recent_requests,
        }
    except Patient.DoesNotExist:
        messages.error(request, 'Patient profile not found. Please contact support.')
        context = {
            'patient': None,
            'total_requests': 0,
            'approved_requests': 0,
            'pending_requests': 0,
            'rejected_requests': 0,
            'total_units_requested': 0,
            'total_approved_units': 0,
            'recent_requests': [],
        }
    
    return render(request, 'patient/patient_dashboard.html', context)

@login_required
def patient_request_view(request):
    if not request.user.groups.filter(name='PATIENT').exists():
        messages.error(request, 'Access denied. Patient account required.')
        return redirect('patientlogin')
    
    try:
        patient = Patient.objects.get(user=request.user)
    except Patient.DoesNotExist:
        messages.error(request, 'Patient profile not found. Please contact support.')
        return redirect('patient-dashboard')
    
    if request.method == 'POST':
        patient_name = request.POST.get('patient_name', '').strip()
        patient_age = request.POST.get('patient_age', '').strip()
        reason = request.POST.get('reason', '').strip()
        bloodgroup = request.POST.get('bloodgroup', '').strip()
        unit = request.POST.get('unit', '').strip()
        
        # Enhanced validation
        errors = []
        
        if not patient_name:
            errors.append('Patient name is required.')
        elif len(patient_name) < 2:
            errors.append('Patient name must be at least 2 characters.')
        
        if not patient_age:
            errors.append('Patient age is required.')
        else:
            try:
                patient_age = int(patient_age)
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
        
        if not unit:
            errors.append('Unit amount is required.')
        else:
            try:
                unit = int(unit)
                if unit < 100 or unit > 500:
                    errors.append('Unit amount must be between 100ml and 500ml.')
            except ValueError:
                errors.append('Please enter a valid unit amount.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'patient/makerequest.html', {'patient': patient})
        
        # Create blood request
        try:
            BloodRequest.objects.create(
                patient=patient,
                patient_name=patient_name,
                patient_age=patient_age,
                reason=reason,
                bloodgroup=bloodgroup,
                unit=unit,
                status='Pending'
            )
            
            messages.success(request, f'Blood request submitted successfully! Requested {unit}ml of {bloodgroup} blood for {patient_name}.')
            return redirect('my-request')
            
        except Exception as e:
            print(f"Error creating blood request: {str(e)}")
            messages.error(request, f'Error submitting request: {str(e)}')
    
    return render(request, 'patient/makerequest.html', {'patient': patient})

@login_required
def patient_request_history_view(request):
    if not request.user.groups.filter(name='PATIENT').exists():
        messages.error(request, 'Access denied. Patient account required.')
        return redirect('patientlogin')
    
    try:
        patient = Patient.objects.get(user=request.user)
        requests = BloodRequest.objects.filter(patient=patient).order_by('-date')
        
        # Calculate statistics
        total_requests = requests.count()
        approved_count = requests.filter(status='Approved').count()
        pending_count = requests.filter(status='Pending').count()
        rejected_count = requests.filter(status='Rejected').count()
        
        # Calculate units
        total_units = requests.aggregate(Sum('unit'))
        total_units_requested = total_units['unit__sum'] if total_units['unit__sum'] else 0
        
        approved_units = requests.filter(status='Approved').aggregate(Sum('unit'))
        total_approved_units = approved_units['unit__sum'] if approved_units['unit__sum'] else 0
        
        context = {
            'requests': requests,
            'total_requests': total_requests,
            'approved_count': approved_count,
            'pending_count': pending_count,
            'rejected_count': rejected_count,
            'total_units_requested': total_units_requested,
            'total_approved_units': total_approved_units,
        }
    except Patient.DoesNotExist:
        messages.error(request, 'Patient profile not found. Please contact support.')
        context = {
            'requests': [],
            'total_requests': 0,
            'approved_count': 0,
            'pending_count': 0,
            'rejected_count': 0,
            'total_units_requested': 0,
            'total_approved_units': 0,
        }
    
    return render(request, 'patient/my_request.html', context)
