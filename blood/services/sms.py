"""AWS SNS powered alert helpers for urgent blood requests."""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from datetime import timedelta
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from donor.models import Donor
from blood.services.donor_recommender import recommend_donors_for_request
from blood.utils.sms_sender import send_sms as send_single_sms
from blood.utils.sms_sender import sanitize_sms_text
from blood.utils.phone import normalize_phone_number

try:  # pragma: no cover - import guard is verified via tests
	import boto3
	from botocore.exceptions import BotoCoreError, ClientError
	from botocore.config import Config
except ImportError:  # pragma: no cover
	boto3 = None

	class BotoCoreError(Exception):
		"""Fallback exception when botocore is unavailable."""

	class ClientError(Exception):
		"""Fallback exception when botocore is unavailable."""


logger = logging.getLogger(__name__)


@dataclass
class AlertResult:
	"""Lightweight summary of an alert dispatch attempt."""

	enabled: bool
	attempted: int
	delivered: int
	recipients: List[str]
	skipped: List[str]
	reason: Optional[str] = None


def notify_matched_donors(blood_request, *, contact_number: Optional[str] = None, sns_client=None) -> AlertResult:
	"""Send urgent SMS alerts to donors that match the request's blood group."""

	if not blood_request.is_urgent:
		return AlertResult(True, 0, 0, [], [], reason="not-urgent")

	if not settings.AWS_SNS_ENABLED:
		logger.info("AWS SNS alerts disabled; skipping urgent request %s", blood_request.id)
		return AlertResult(False, 0, 0, [], [], reason="sns-disabled")

	if sns_client is None:
		sns_client = _get_sns_client()

	donors = _select_donors_for_alert(blood_request)
	if not donors:
		logger.warning("No donors eligible for urgent request %s (%s)", blood_request.id, blood_request.bloodgroup)
		return AlertResult(True, 0, 0, [], [], reason="no-donors")

	message = _build_message(blood_request, contact_number)
	message = sanitize_sms_text(message)
	attributes = _message_attributes()

	sent_to: List[str] = []
	skipped: List[str] = []
	publish_count = 0
	now = timezone.now()
	started = time.perf_counter()

	for donor, phone in donors:
		try:
			sns_client.publish(PhoneNumber=phone, Message=message, MessageAttributes=attributes)
		except (BotoCoreError, ClientError) as exc:  # pragma: no cover - network errors not deterministic
			skipped.append(phone)
			logger.error(
				"Failed to publish urgent alert for request %s to donor %s (phone: %s): %s",
				blood_request.id,
				donor.id,
				phone,
				exc,
			)
			continue

		sent_to.append(phone)
		publish_count += 1
		Donor.objects.filter(pk=donor.pk).update(last_notified_at=now)

	duration_ms = int((time.perf_counter() - started) * 1000)
	logger.info(
		"Urgent SNS alert dispatch finished for request %s: attempted=%s delivered=%s duration_ms=%s",
		blood_request.id,
		len(donors),
		publish_count,
		duration_ms,
	)
	return AlertResult(True, len(donors), publish_count, sent_to, skipped)


def send_requester_confirmation(
	blood_request,
	contact_number: Optional[str],
	*,
	sms_sender=send_single_sms,
):
	"""Send a confirmation SMS back to the requester with their request ID."""

	if not contact_number:
		return {'status': 'skipped', 'reason': 'no-contact'}

	normalized = _normalize_phone_number(contact_number)
	if not normalized:
		return {'status': 'skipped', 'reason': 'invalid-contact'}

	if not settings.AWS_SNS_ENABLED:
		logger.info(
			"AWS SNS alerts disabled; skipping requester confirmation for %s",
			blood_request.id,
		)
		return {'status': 'skipped', 'reason': 'sns-disabled'}

	message = _build_requester_confirmation_message(blood_request)

	try:
		response = sms_sender(normalized, message)
		if response.get('status') != 'success':
			logger.error(
				"Requester confirmation SMS failed for %s: %s",
				blood_request.id,
				response,
			)
		return response
	except Exception as exc:  # pragma: no cover - network/credentials issues
		logger.error(
			"Error sending requester confirmation for %s: %s",
			blood_request.id,
			exc,
		)
		return {'status': 'error', 'reason': str(exc)}



@lru_cache(maxsize=1)
def _get_sns_client():
	if boto3 is None:
		raise RuntimeError("boto3 is required to send SNS alerts")
	connect_timeout = int(getattr(settings, "AWS_SNS_CONNECT_TIMEOUT", 3))
	read_timeout = int(getattr(settings, "AWS_SNS_READ_TIMEOUT", 10))
	max_attempts = int(getattr(settings, "AWS_SNS_MAX_ATTEMPTS", 2))
	config = Config(
		connect_timeout=connect_timeout,
		read_timeout=read_timeout,
		retries={"max_attempts": max_attempts, "mode": "standard"},
	)
	return boto3.client('sns', region_name=settings.AWS_SNS_REGION, config=config)


def _select_donors_for_alert(blood_request) -> Sequence[Tuple[Donor, str]]:
	base_queryset = (
		Donor.objects.filter(
			bloodgroup=blood_request.bloodgroup,
			is_available=True,
		)
		.exclude(Q(mobile__isnull=True) | Q(mobile__exact=""))
	)
	
	total_candidates = base_queryset.count()
	logger.info(f"Found {total_candidates} available donors for blood group {blood_request.bloodgroup}")

	gap_seconds = max(settings.AWS_SNS_MIN_NOTIFICATION_GAP_SECONDS, 0)
	if gap_seconds:
		cutoff = timezone.now() - timedelta(seconds=gap_seconds)
		base_queryset = base_queryset.filter(Q(last_notified_at__lt=cutoff) | Q(last_notified_at__isnull=True))
	
	filtered_candidates = base_queryset.count()
	if total_candidates > filtered_candidates:
		logger.info(f"Skipped {total_candidates - filtered_candidates} donors due to {gap_seconds}s cooldown")

	zipcode = blood_request.request_zipcode or ""
	ordered_queryset = base_queryset.annotate(
		zip_match=Case(
			When(zipcode=zipcode, then=Value(0)),
			default=Value(1),
			output_field=IntegerField(),
		)
	).order_by('zip_match', 'last_notified_at', 'id')

	max_recipients = int(getattr(settings, "AWS_SNS_MAX_RECIPIENTS", 0) or 0)
	unlimited_recipients = max_recipients <= 0
	donors: List[Tuple[Donor, str]] = []
	seen_numbers = set()
	
	skipped_invalid = 0
	queryset_to_scan = ordered_queryset if unlimited_recipients else ordered_queryset[: max_recipients * 2]
	for donor in queryset_to_scan:  # light over-fetch in limited mode to offset formatting skips
		formatted = _normalize_phone_number(donor.mobile)
		if not formatted:
			skipped_invalid += 1
			continue
		if formatted in seen_numbers:
			continue
		donors.append((donor, formatted))
		seen_numbers.add(formatted)
		if (not unlimited_recipients) and len(donors) >= max_recipients:
			break
			
	if skipped_invalid > 0:
		logger.warning(f"Skipped {skipped_invalid} donors due to invalid phone numbers")
		
	return donors


def _build_message(blood_request, contact_number: Optional[str]) -> str:
	contact = _resolve_contact_number(blood_request, contact_number)
	zipcode = blood_request.request_zipcode or "unknown area"
	base = (
		f"Urgent {blood_request.bloodgroup} blood request for {blood_request.patient_name} "
		f"({blood_request.unit}ml) near {zipcode}."
	)
	details = " Reply available to confirm via donor portal."
	if contact:
		details = f" Contact {contact} if you can donate." + details
	return f"{base}{details}"[:1200]  # safeguard against overly long messages


def _build_requester_confirmation_message(blood_request) -> str:
	return (
		f"BloodBridge Alert #{blood_request.id}: We received your {blood_request.bloodgroup} "
		f"request for {blood_request.unit}ml. Our donor network has been notified. "
		"Stay available for coordinator follow-ups."
	)


def _resolve_contact_number(blood_request, explicit: Optional[str]) -> Optional[str]:
	if explicit:
		return explicit
	patient = getattr(blood_request, 'patient', None)
	if patient and getattr(patient, 'mobile', None):
		return patient.mobile
	donor = getattr(blood_request, 'request_by_donor', None)
	if donor and donor.mobile:
		return donor.mobile
	if getattr(blood_request, 'reason', None):
		extracted = _extract_contact_number_from_reason(blood_request.reason)
		if extracted:
			return extracted
	return None


def notify_request_approved(
	blood_request,
	*,
	sms_sender=send_single_sms,
):
	"""Notify patient and top recommended donor when an admin approves a request."""

	if not settings.AWS_SNS_ENABLED:
		logger.info("AWS SNS alerts disabled; skipping approval SMS for request %s", blood_request.id)
		return {"status": "skipped", "reason": "sns-disabled"}

	total_started = time.perf_counter()
	raw_patient_phone = _resolve_contact_number(blood_request, None)
	patient_phone = _normalize_phone_number(raw_patient_phone)
	patient_result = None

	rec_started = time.perf_counter()
	recommendations = recommend_donors_for_request(blood_request, limit=1, require_eligible=True)
	recommendation_ms = int((time.perf_counter() - rec_started) * 1000)
	top_rec = recommendations[0] if recommendations else None

	if patient_phone:
		message = _build_patient_approved_message(blood_request, top_rec)
		try:
			patient_result = sms_sender(patient_phone, message)
			if isinstance(patient_result, dict):
				patient_result = {**patient_result, "to": patient_phone}
			if patient_result.get("status") != "success":
				logger.error("Patient approval SMS failed for %s: %s", blood_request.id, patient_result)
		except Exception as exc:  # pragma: no cover - network/credentials issues
			logger.error("Error sending patient approval SMS for %s: %s", blood_request.id, exc)
			patient_result = {"status": "error", "reason": str(exc), "to": patient_phone}
	else:
		logger.warning(
			"Skipping patient approval SMS for request %s (patient: %s). Missing/invalid phone: %s",
			blood_request.id,
			getattr(blood_request, "patient_name", "unknown"),
			raw_patient_phone,
		)
		patient_result = {"status": "skipped", "reason": "no-patient-contact"}

	donor_result = None
	if top_rec is None:
		donor_result = {"status": "skipped", "reason": "no-recommendations"}
	else:
		donor_phone = _normalize_phone_number(getattr(top_rec.donor, "mobile", None))
		if donor_phone:
			message = _build_donor_approved_message(blood_request, top_rec)
			try:
				donor_result = sms_sender(donor_phone, message)
				if isinstance(donor_result, dict):
					donor_result = {**donor_result, "to": donor_phone}
				if donor_result.get("status") != "success":
					logger.error("Donor approval SMS failed for %s: %s", blood_request.id, donor_result)
			except Exception as exc:  # pragma: no cover - network/credentials issues
				logger.error("Error sending donor approval SMS for %s: %s", blood_request.id, exc)
				donor_result = {"status": "error", "reason": str(exc), "to": donor_phone}
		else:
			donor_result = {"status": "skipped", "reason": "invalid-donor-phone"}


	logger.info(
		"Approval SMS dispatch result for request %s: patient=%s donor=%s rec_ms=%s",
		blood_request.id,
		(patient_result or {}).get("status"),
		(donor_result or {}).get("status"),
		recommendation_ms,
	)

	total_ms = int((time.perf_counter() - total_started) * 1000)
	return {
		"status": "sent",
		"patient": patient_result,
		"donor": donor_result,
		"timing": {"recommendation_ms": recommendation_ms, "total_ms": total_ms},
	}


def notify_request_rejected(
	blood_request,
	*,
	reason: Optional[str] = None,
	sms_sender=send_single_sms,
):
	"""Notify patient when an admin rejects a request."""

	if not settings.AWS_SNS_ENABLED:
		logger.info("AWS SNS alerts disabled; skipping rejection SMS for request %s", blood_request.id)
		return {"status": "skipped", "reason": "sns-disabled"}

	raw_patient_phone = _resolve_contact_number(blood_request, None)
	patient_phone = _normalize_phone_number(raw_patient_phone)
	if not patient_phone:
		logger.warning(
			"Skipping patient rejection SMS for request %s (patient: %s). Missing/invalid phone: %s",
			blood_request.id,
			getattr(blood_request, "patient_name", "unknown"),
			raw_patient_phone,
		)
		return {"status": "skipped", "reason": "no-patient-contact"}

	message = _build_patient_rejected_message(blood_request, reason)
	try:
		response = sms_sender(patient_phone, message)
		if response.get("status") != "success":
			logger.error("Patient rejection SMS failed for %s: %s", blood_request.id, response)
		return response
	except Exception as exc:  # pragma: no cover - network/credentials issues
		logger.error("Error sending patient rejection SMS for %s: %s", blood_request.id, exc)
		return {"status": "error", "reason": str(exc)}


def notify_donation_approved(
	donation,
	*,
	sms_sender=send_single_sms,
):
	"""Notify donor when an admin approves a donation."""

	if not settings.AWS_SNS_ENABLED:
		logger.info("AWS SNS alerts disabled; skipping donation approval SMS for %s", donation.id)
		return {"status": "skipped", "reason": "sns-disabled"}

	raw_phone = getattr(donation.donor, "mobile", None)
	phone = _normalize_phone_number(raw_phone)
	if not phone:
		logger.warning(
			"Skipping donation approval SMS for donation %s (donor: %s). Missing/invalid phone: %s",
			donation.id,
			getattr(donation.donor, "get_name", "unknown"),
			raw_phone,
		)
		return {"status": "skipped", "reason": "no-donor-contact"}

	message = _build_donation_approved_message(donation)
	try:
		response = sms_sender(phone, message)
		if response.get("status") != "success":
			logger.error("Donor approval SMS failed for donation %s: %s", donation.id, response)
		return response
	except Exception as exc:  # pragma: no cover - network/credentials issues
		logger.error("Error sending donor approval SMS for donation %s: %s", donation.id, exc)
		return {"status": "error", "reason": str(exc)}


def notify_donation_rejected(
	donation,
	*,
	reason: Optional[str] = None,
	sms_sender=send_single_sms,
):
	"""Notify donor when an admin rejects a donation."""

	if not settings.AWS_SNS_ENABLED:
		logger.info("AWS SNS alerts disabled; skipping donation rejection SMS for %s", donation.id)
		return {"status": "skipped", "reason": "sns-disabled"}

	raw_phone = getattr(donation.donor, "mobile", None)
	phone = _normalize_phone_number(raw_phone)
	if not phone:
		logger.warning(
			"Skipping donation rejection SMS for donation %s (donor: %s). Missing/invalid phone: %s",
			donation.id,
			getattr(donation.donor, "get_name", "unknown"),
			raw_phone,
		)
		return {"status": "skipped", "reason": "no-donor-contact"}

	message = _build_donation_rejected_message(donation, reason)
	try:
		response = sms_sender(phone, message)
		if response.get("status") != "success":
			logger.error("Donor rejection SMS failed for donation %s: %s", donation.id, response)
		return response
	except Exception as exc:  # pragma: no cover - network/credentials issues
		logger.error("Error sending donor rejection SMS for donation %s: %s", donation.id, exc)
		return {"status": "error", "reason": str(exc)}


def _message_attributes():
	attributes = {
		'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': settings.AWS_SNS_SMS_TYPE},
	}
	if settings.AWS_SNS_SENDER_ID:
		attributes['AWS.SNS.SMS.SenderID'] = {
			'DataType': 'String',
			'StringValue': settings.AWS_SNS_SENDER_ID[:11],
		}
	return attributes


def _normalize_phone_number(raw: Optional[str]) -> Optional[str]:
	# Backwards-compatible wrapper.
	return normalize_phone_number(raw)


def _extract_contact_number_from_reason(reason: str) -> Optional[str]:
	match = re.search(r"Contact:\s*([^\n]+)", reason or "")
	if not match:
		return None
	return _normalize_phone_number(match.group(1).strip())


def _build_patient_approved_message(blood_request, top_rec) -> str:
	patient_name = blood_request.patient_name
	base = (
		f"BloodBridge Update: Your request #{blood_request.id} for {blood_request.bloodgroup} "
		f"({blood_request.unit}ml) has been approved, {patient_name}."
	)
	if not top_rec:
		return f"{base} Our team will contact you with donor details shortly."[:1200]

	donor = top_rec.donor
	phone = _normalize_phone_number(getattr(donor, "mobile", None)) or "N/A"
	address = getattr(donor, "address", "") or "N/A"
	availability = "Available" if donor.is_available else "Unavailable"
	message = (
		f"{base} "
		f"Top matched donor: {donor.get_name} ({donor.bloodgroup}). "
		f"Phone: {phone}. Address: {address}. Status: {availability}. "
		f"Recommendation score: {top_rec.score:.1f}."
	)
	return message[:1200]


def _build_donor_approved_message(blood_request, top_rec) -> str:
	donor = top_rec.donor
	patient_contact = _resolve_contact_number(blood_request, None) or "N/A"
	reason = (blood_request.reason or "").split("\n", 1)[0].strip()
	if reason:
		reason = f" Reason: {reason}."
	message = (
		"BloodBridge Alert: You are the top recommended donor for an approved request. "
		f"Patient: {blood_request.patient_name}, Age: {blood_request.patient_age}, "
		f"Blood: {blood_request.bloodgroup}, Units: {blood_request.unit}ml."
		f" Contact: {patient_contact}.{reason}"
		" Please coordinate with the patient or admin promptly."
	)
	return message[:1200]


def _build_patient_rejected_message(blood_request, reason: Optional[str]) -> str:
	patient_name = blood_request.patient_name
	rejection_reason = reason or "Request could not be fulfilled at this time."
	message = (
		f"BloodBridge Update: Your request #{blood_request.id} for {blood_request.bloodgroup} "
		f"({blood_request.unit}ml) was rejected. Reason: {rejection_reason}. "
		f"We wish you a speedy recovery and good health, {patient_name}."
	)
	return message[:1200]


def _build_donation_approved_message(donation) -> str:
	message = (
		f"BloodBridge Update: Your blood donation #{donation.id} of {donation.unit}ml "
		f"({donation.bloodgroup}) has been approved. Thank you for saving lives!"
	)
	return message[:1200]


def _build_donation_rejected_message(donation, reason: Optional[str]) -> str:
	rejection_reason = reason or "Donation could not be accepted at this time."
	message = (
		f"BloodBridge Update: Your blood donation #{donation.id} of {donation.unit}ml "
		f"({donation.bloodgroup}) was rejected. Reason: {rejection_reason}. "
		"Thank you for your willingness to help."
	)
	return message[:1200]

