import logging
from typing import Optional

logger = logging.getLogger(__name__)

def send_push_notification(
    device_token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    notification_type: str = "general"
) -> bool:
    """
    Send Firebase push notification.
    Falls back to logging when Firebase credentials not configured.
    """
    if not device_token:
        return False

    from app.config import settings

    # Try Firebase Admin SDK
    try:
        import firebase_admin
        from firebase_admin import messaging, credentials

        firebase_creds = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT', None)

        if firebase_creds and firebase_creds not in ('', '{}'):
            # Initialize if not already done
            if not firebase_admin._apps:
                import json
                cred_dict = json.loads(firebase_creds) if isinstance(firebase_creds, str) else firebase_creds
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)

            merged_data = {**(data or {}), "type": notification_type}
            # iOS app-icon badge = unread count when the caller supplied it.
            try:
                badge = int(merged_data.get("badge", 1))
            except (TypeError, ValueError):
                badge = 1

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=merged_data,
                token=device_token,
                android=messaging.AndroidConfig(
                    notification=messaging.AndroidNotification(
                        icon="notification_icon",
                        color="#16A344",
                        sound="default",
                        channel_id="rupexi_default",
                    ),
                    priority="high",
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", badge=badge)
                    )
                ),
            )
            messaging.send(message)
            return True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"FCM send failed: {e}")

    # Development fallback — just log it
    logger.info(f"[FCM MOCK] To: {device_token[:20]}... | {title}: {body}")
    return True


def send_bulk_notification(
    device_tokens: list[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> dict:
    """Send to multiple devices, returns success/failure counts"""
    success_count = 0
    fail_count = 0
    for token in device_tokens:
        if send_push_notification(token, title, body, data):
            success_count += 1
        else:
            fail_count += 1
    return {"success": success_count, "failed": fail_count}
