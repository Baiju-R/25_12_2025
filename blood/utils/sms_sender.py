"""Simple SNS SMS helper used by approval/rejection notifications.

This module intentionally keeps a small surface area and returns structured
dicts so callers can log or present outcomes without crashing the request.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config
from django.conf import settings


logger = logging.getLogger(__name__)


_DISALLOWED_SMS_CHARS_TRANSLATION = str.maketrans({
    "[": "(",
    "]": ")",
    "{": "(",
    "}": ")",
    "<": "(",
    ">": ")",
    "\\": " ",
    "|": " ",
    "^": " ",
    "~": " ",
    "`": " ",
})


def sanitize_sms_text(text: str) -> str:
    """Normalize SMS text to be display-safe across devices/carriers.

    Some carriers mishandle special punctuation (including certain GSM-7 extension
    characters like '[' and ']'). We normalize to plain ASCII and replace a small
    set of problematic characters.
    """

    if text is None:
        return ""

    # Normalize Unicode -> ASCII.
    normalized = unicodedata.normalize("NFKD", str(text))
    normalized = normalized.encode("ascii", "ignore").decode("ascii", "ignore")

    # Collapse whitespace/newlines and replace problematic punctuation.
    normalized = normalized.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    normalized = normalized.translate(_DISALLOWED_SMS_CHARS_TRANSLATION)

    # Keep only common printable characters to reduce carrier rendering issues.
    normalized = re.sub(r"[^A-Za-z0-9 .,:;!?@#%&()\-+/=_']+", " ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


@lru_cache(maxsize=1)
def _get_sns_client():
    connect_timeout = int(getattr(settings, "AWS_SNS_CONNECT_TIMEOUT", 3))
    read_timeout = int(getattr(settings, "AWS_SNS_READ_TIMEOUT", 10))
    max_attempts = int(getattr(settings, "AWS_SNS_MAX_ATTEMPTS", 2))

    config = Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "standard"},
    )

    return boto3.client("sns", region_name=settings.AWS_SNS_REGION, config=config)


def send_sms(phone: str, message: str):
    """Send a one-off SMS via AWS SNS."""

    sns = _get_sns_client()
    message = sanitize_sms_text(message)

    attributes = {
        'AWS.SNS.SMS.SMSType': {
            'DataType': 'String',
            'StringValue': getattr(settings, 'AWS_SNS_SMS_TYPE', 'Transactional'),
        }
    }
    sender_id = getattr(settings, 'AWS_SNS_SENDER_ID', '')
    if sender_id:
        attributes['AWS.SNS.SMS.SenderID'] = {
            'DataType': 'String',
            'StringValue': str(sender_id)[:11],
        }

    try:
        started = time.perf_counter()
        response = sns.publish(
            PhoneNumber=phone,
            Message=message,
            MessageAttributes=attributes,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "status": "success",
            "provider": "aws-sns",
            "region": getattr(settings, "AWS_SNS_REGION", None),
            "duration_ms": duration_ms,
            "message_id": response.get("MessageId"),
            "response": response,
        }
    except (ClientError, BotoCoreError) as exc:
        logger.error("SNS publish failed to %s: %s", phone, exc)
        return {"status": "error", "provider": "aws-sns", "message": str(exc)}
