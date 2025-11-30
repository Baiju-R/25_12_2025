from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseRedirect
from . import forms, models
from django.db.models import Sum, Q
from django.contrib.auth.models import Group, User
from datetime import date, timedelta
from donor import models as dmodels
from patient import models as pmodels
from donor import forms as dforms
from patient import forms as pforms

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
    return render(request, 'blood/index.html')

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
def update_donor_view(request, pk):
    if not request.user.is_superuser:
        return redirect('adminlogin')
    donor = dmodels.Donor.objects.get(id=pk)
    user = User.objects.get(id=donor.user_id)
    userForm = dforms.DonorUserForm(instance=user)
    donorForm = dforms.DonorForm(request.FILES, instance=donor)
    mydict = {'userForm': userForm, 'donorForm': donorForm}
    if request.method == 'POST':
        userForm = dforms.DonorUserForm(request.POST, instance=user)
        donorForm = dforms.DonorForm(request.POST, request.FILES, instance=donor)
        if userForm.is_valid() and donorForm.is_valid():
            user = userForm.save()
            user.set_password(user.password)
            user.save()
            donor = donorForm.save(commit=False)
            donor.user = user
            donor.bloodgroup = donorForm.cleaned_data['bloodgroup']
            donor.save()
            return redirect('admin-donor')
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
    userForm = pforms.PatientUserForm(instance=user)
    patientForm = pforms.PatientForm(request.FILES, instance=patient)
    mydict = {'userForm': userForm, 'patientForm': patientForm}
    if request.method == 'POST':
        userForm = pforms.PatientUserForm(request.POST, instance=user)
        patientForm = pforms.PatientForm(request.POST, request.FILES, instance=patient)
        if userForm.is_valid() and patientForm.is_valid():
            user = userForm.save()
            user.set_password(user.password)
            user.save()
            patient = patientForm.save(commit=False)
            patient.user = user
            patient.bloodgroup = patientForm.cleaned_data['bloodgroup']
            patient.save()
            return redirect('admin-patient')
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

def quick_request_view(request):
    """Allow anonymous users to make quick blood requests"""
    if request.method == 'POST':
        # Get form data
        patient_name = request.POST.get('patient_name', '').strip()
        patient_age = request.POST.get('patient_age', '').strip()
        reason = request.POST.get('reason', '').strip()
        bloodgroup = request.POST.get('bloodgroup', '').strip()
        unit = request.POST.get('unit', '').strip()
        contact_number = request.POST.get('contact_number', '').strip()
        emergency_contact = request.POST.get('emergency_contact', '').strip()
        
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
        
        if not contact_number:
            errors.append('Contact number is required.')
        elif len(contact_number) < 10:
            errors.append('Please provide a valid contact number.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'patient_name': patient_name,
                'patient_age': patient_age,
                'reason': reason,
                'bloodgroup': bloodgroup,
                'unit': unit,
                'contact_number': contact_number,
                'emergency_contact': emergency_contact,
            }
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
                status='Pending'
            )
            
            messages.success(
                request, 
                f'🩸 Emergency Blood Request Submitted Successfully!\n\n'
                f'Request ID: #{blood_request.id}\n'
                f'Patient: {patient_name}\n'
                f'Blood Group: {bloodgroup}\n'
                f'Units: {unit}ml\n\n'
                f'⚡ This is a priority request that will be processed immediately.\n'
                f'Our team will contact you at {contact_number} within 30 minutes.\n\n'
                f'Please keep this Request ID for reference: #{blood_request.id}'
            )
            
            # Log the quick request for admin monitoring
            print(f"QUICK REQUEST SUBMITTED - ID: {blood_request.id}, "
                  f"Patient: {patient_name}, Blood Group: {bloodgroup}, "
                  f"Units: {unit}ml, Contact: {contact_number}")
            
            # Redirect to success page with request ID
            return redirect('quick-request-success', request_id=blood_request.id)
            
        except Exception as e:
            print(f"Error creating quick blood request: {str(e)}")
            messages.error(request, f'Error submitting request: {str(e)}')
    
    return render(request, 'blood/quick_request.html')

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