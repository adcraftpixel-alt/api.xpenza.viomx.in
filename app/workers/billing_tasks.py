from celery import shared_task
import logging

logger = logging.getLogger(__name__)


def get_db_session():
    from app.database import SessionLocal
    return SessionLocal()


@shared_task(name="app.workers.billing_tasks.sync_unsynced_hub_subscriptions")
def sync_unsynced_hub_subscriptions():
    """Retry the Control Hub purchase report for any trialing/active
    subscription that never got confirmed as synced (hub_synced_at still
    null — see BillingService._report_purchase_to_hub / _retry_hub_sync).

    Today that retry only happens when the affected user calls
    GET /billing/subscription (e.g. opening the app), so a user who never
    comes back after a failed webhook-time sync leaves the Hub permanently
    unaware of their purchase. This sweep closes that gap independent of
    user activity.
    """
    from app.models.billing import UserSubscription
    from app.api.v1.billing.service import billing_service

    db = get_db_session()
    try:
        unsynced = db.query(UserSubscription).filter(
            UserSubscription.status.in_(("trialing", "active")),
            UserSubscription.hub_synced_at.is_(None),
        ).all()

        synced = 0
        for sub in unsynced:
            billing_service._retry_hub_sync(sub.id, db)
            db.refresh(sub)
            if sub.hub_synced_at:
                synced += 1

        logger.info(
            "sync_unsynced_hub_subscriptions: %d/%d synced", synced, len(unsynced)
        )
        return {"checked": len(unsynced), "synced": synced}
    except Exception as e:
        logger.error(f"sync_unsynced_hub_subscriptions error: {e}")
        return {"error": str(e)}
    finally:
        db.close()
