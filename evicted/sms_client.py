"""SMS client using Twilio to send SMS directly.

Configure these env vars (in .env or Railway Variables):
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM_NUMBER  (your Twilio phone number, in E.164 format, e.g. +15005550006)
"""
import logging
import os

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

logger = logging.getLogger(__name__)


def send_sms(phone_number: str, message: str) -> bool:
    """Send an SMS directly via Twilio. Returns True on success, False otherwise."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")

    if not account_sid or not auth_token or not from_number:
        logger.warning("Twilio SMS not configured (missing SID/token/from number). Skipping send.")
        return False

    try:
        client = Client(account_sid, auth_token)
        client.messages.create(
            to=phone_number,
            from_=from_number,
            body=message,
        )
        logger.info("Twilio SMS sent to %s", phone_number)
        return True
    except TwilioRestException as e:
        logger.exception("Twilio SMS error for %s: %s", phone_number, e)
        return False

