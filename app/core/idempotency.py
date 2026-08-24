from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.idempotency import IdempotencyKey


def get_cached_response(db: Session, user_id: str, key: str | None, endpoint: str):
    """Return the stored response for a prior request with this idempotency
    key, or None if this is a new request (no key supplied, or no match yet)."""
    if not key:
        return None
    row = (
        db.query(IdempotencyKey)
        .filter(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.key == key,
        )
        .first()
    )
    return row.response_json if row else None


def store_response(db: Session, user_id: str, key: str | None, endpoint: str, response_json) -> None:
    """Persist the response for this idempotency key so a client retry (e.g.
    after giving up on a slow AI-categorized save) replays the original
    result instead of creating a duplicate expense."""
    if not key:
        return
    try:
        db.add(IdempotencyKey(user_id=user_id, endpoint=endpoint, key=key, response_json=response_json))
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent identical request — its row already
        # holds the canonical response, nothing more to store.
        db.rollback()
