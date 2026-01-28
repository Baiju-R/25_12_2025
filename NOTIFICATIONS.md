# SMS Notification Scenarios

This document outlines all automatic SMS notifications triggered by the Blood Bank Management System.

## 1. New Blood Request (Matching Engine)
**Trigger:** A new blood request is submitted by a Patient or Donor.
**Target:** Compatible Donors nearby.
**Content:**
> URGENT: Blood Needed! {bloodgroup} required at {hospital} ({city}). Please contact us if available.

**Code:** `blood.services.sms.notify_matched_donors`
**Queued Task:** `blood.tasks.send_urgent_alerts`
**Call Sites:** Patient Request, Donor Request, Admin Quick Request.

## 2. Request Approved
**Trigger:** Admin approves a pending `BloodRequest` in the dashboard.
**Target:**
1. **Patient:**
> Your request for {bloodgroup} blood at {hospital} has been APPROVED by the blood bank admin.
2. **Donor (if request made by donor):**
> Update: The blood request you submitted for {bloodgroup} has been APPROVED.

**Code:** `blood.services.sms.notify_request_approved`
**Queued Task:** `blood.tasks.send_request_approved_sms`
**Call Sites:** Admin Dashboard (`update_approve_status_view`).

## 3. Request Rejected
**Trigger:** Admin rejects a pending `BloodRequest`.
**Target:** Patient or Donor (Requestor).
**Content:**
> Update: Your request for {bloodgroup} blood has been declined by the system. Reason: Administrative decision.

**Code:** `blood.services.sms.notify_request_rejected`
**Queued Task:** `blood.tasks.send_request_rejected_sms`

## 4. Donation Approved
**Trigger:** Admin approves a pending `BloodDonate` entry.
**Target:** The Donor who donated.
**Content:**
> Thank you {name}! Your donation of {bloodgroup} blood has been verified and approved. You saved a life today!

**Code:** `blood.services.sms.notify_donation_approved`
**Queued Task:** `blood.tasks.send_donation_approved_sms`
**Call Sites:** Admin Donation Dashboard (`approve_donation_view`).

## 5. Donation Rejected
**Trigger:** Admin rejects a `BloodDonate` entry.
**Target:** The Donor.
**Content:**
> Notice: Your recent blood donation entry was not approved. Please contact admin for details.

**Code:** `blood.services.sms.notify_donation_rejected`
**Queued Task:** `blood.tasks.send_donation_rejected_sms`

---

## Technical Notes

- **Sender ID:** None (Uses AWS Default/Random) to ensure delivery in India (DLT Compliance).
- **Phone Formatting:** Automatic E.164 normalization (+91...).
- **Delivery:** Transactional SMS via AWS SNS (ap-south-1).

## Background Sending (Celery)

By default, the web request *enqueues* SMS work to Celery so pages return faster and SNS latency doesn't block the UI.

### Environment variables

- `CELERY_BROKER_URL` (default `redis://localhost:6379/0`)
- `CELERY_RESULT_BACKEND` (default = broker URL)

### Run Redis

- If you have Docker: `docker run -p 6379:6379 redis:7`
- Or run any local Redis service on port `6379`.

### Run the worker (Windows)

Use `--pool=solo` on Windows:

- `celery -A bloodbankmanagement worker -l info --pool=solo`

### Dev fallback (no Redis/worker)

If you want to run everything inline (useful for local dev/tests), set:

- `CELERY_TASK_ALWAYS_EAGER=true`

In this mode, tasks execute immediately in-process (no background speedup), but the codepaths stay identical.
