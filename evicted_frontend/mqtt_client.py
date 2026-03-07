"""
MQTT client for publishing SMS events to a broker.
A separate subscriber can consume these messages and call an SMS API.
Supports HiveMQ Cloud (TLS + username/password).
"""
import json
import logging
import ssl

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)


def publish_sms_event(phone_number: str, message: str, **extra) -> bool:
    """
    Publish an SMS event to the MQTT broker. The payload is a signal for
    another service to send an SMS to the given phone number.

    Args:
        phone_number: Destination phone number (E.164 recommended).
        message: SMS body text.
        **extra: Optional keys (e.g. ref_id, lot_number) included in payload.

    Returns:
        True if publish succeeded, False otherwise.
    """
    payload = {
        "phone_number": phone_number,
        "message": message,
        **extra,
    }
    topic = getattr(settings, "MQTT_TOPIC_SMS", "evicted/sms/send")
    host = getattr(settings, "MQTT_BROKER_HOST", "localhost")
    port = int(getattr(settings, "MQTT_BROKER_PORT", 1883))
    use_tls = getattr(settings, "MQTT_USE_TLS", False)
    client_id = getattr(settings, "MQTT_CLIENT_ID", "evicted-frontend")
    username = getattr(settings, "MQTT_USERNAME", None) or None
    password = getattr(settings, "MQTT_PASSWORD", None) or None

    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    if username and password:
        client.username_pw_set(username, password)
    if use_tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(False)

    try:
        client.connect(host, port=port, keepalive=60)
        client.loop_start()
        result = client.publish(topic, json.dumps(payload), qos=1)
        result.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info("SMS event published to %s for %s", topic, phone_number)
            return True
        logger.warning("MQTT publish failed: rc=%s", result.rc)
        return False
    except Exception as e:
        logger.exception("MQTT publish error: %s", e)
        return False
