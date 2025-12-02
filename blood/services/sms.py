"""AWS SNS powered alert helpers for urgent blood requests."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from donor.models import Donor
from blood.utils.sms_sender import send_sms as send_single_sms

try:  # pragma: no cover - import guard is verified via tests
	import boto3
	from botocore.exceptions import BotoCoreError, ClientError
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
	attributes = _message_attributes()

	sent_to: List[str] = []
	skipped: List[str] = []
	publish_count = 0
	now = timezone.now()

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

	if not settings.AWS_SNS_ENABLED:
		logger.info(
			"AWS SNS alerts disabled; skipping requester confirmation for %s",
			blood_request.id,
		)
		return {'status': 'skipped', 'reason': 'sns-disabled'}

	message = _build_requester_confirmation_message(blood_request)

	try:
		response = sms_sender(contact_number, message)
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


def _get_sns_client():
	if boto3 is None:
		raise RuntimeError("boto3 is required to send SNS alerts")
	return boto3.client('sns', region_name=settings.AWS_SNS_REGION)


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

	max_recipients = max(settings.AWS_SNS_MAX_RECIPIENTS, 1)
	donors: List[Tuple[Donor, str]] = []
	seen_numbers = set()
	
	skipped_invalid = 0
	for donor in ordered_queryset[: max_recipients * 2]:  # light over-fetch to offset formatting skips
		formatted = _normalize_phone_number(donor.mobile)
		if not formatted:
			skipped_invalid += 1
			continue
		if formatted in seen_numbers:
			continue
		donors.append((donor, formatted))
		seen_numbers.add(formatted)
		if len(donors) >= max_recipients:
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
	return None


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
	if not raw:
		return None
	cleaned = re.sub(r"[\s\-()]+", "", raw)
	if cleaned.startswith('+'):
		digits = '+' + re.sub(r"[^0-9]", "", cleaned)
		return digits if len(digits) >= 8 else None
	digits_only = re.sub(r"[^0-9]", "", cleaned)
	if not digits_only:
		return None
	default_code = settings.AWS_SNS_DEFAULT_COUNTRY_CODE or '+1'
	if not default_code.startswith('+'):
		default_code = f'+{default_code}'
	if digits_only.startswith(default_code.lstrip('+')):
		return f'+{digits_only}'
	return f'{default_code}{digits_only}'

