"""Simple SNS SMS helper for manual testing endpoints."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

sns = boto3.client("sns", region_name=settings.AWS_SNS_REGION)


def send_sms(phone: str, message: str):
    """Send a one-off SMS via AWS SNS."""

    try:
        response = sns.publish(
            PhoneNumber=phone,
            Message=message,
            MessageAttributes={
                'AWS.SNS.SMS.SMSType': {
                    'DataType': 'String',
                    'StringValue': 'Transactional'
                }
            }
        )
        return {"status": "success", "response": response}
    except ClientError as exc:
        return {"status": "error", "message": str(exc)}
