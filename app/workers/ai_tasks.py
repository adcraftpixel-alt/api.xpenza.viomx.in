from celery import shared_task
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

def get_db_session():
    from app.database import SessionLocal
    return SessionLocal()

@shared_task(name="app.workers.ai_tasks.generate_all_user_insights")
def generate_all_user_insights():
    """Run nightly for all active users"""
    db = get_db_session()
    try:
        users = db.execute(text("""
            SELECT id FROM users WHERE is_active = true AND onboarding_done = true
        """)).fetchall()

        generated = 0
        for user in users:
            try:
                generate_user_insights.delay(str(user.id))
                generated += 1
            except Exception as e:
                logger.warning(f"Failed to queue insights for {user.id}: {e}")

        logger.info(f"Queued insights for {generated} users")
        return {"users_queued": generated}
    finally:
        db.close()

@shared_task(name="app.workers.ai_tasks.generate_user_insights")
def generate_user_insights(user_id: str):
    """Generate and store AI insights for one user"""
    import httpx
    try:
        # Call AI microservice
        response = httpx.get(
            f"http://localhost:8001/api/v1/insights?user_id={user_id}",
            timeout=30.0
        )
        if response.status_code == 200:
            insights_data = response.json().get("data", [])

            db = get_db_session()
            try:
                import uuid, json
                for insight in insights_data[:5]:  # max 5 per run
                    db.execute(text("""
                        INSERT INTO ai_insights (id, user_id, type, title, body, data, created_at)
                        VALUES (:id, :uid, :type, :title, :body, :data::jsonb, NOW())
                    """), {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "type": insight.get("type", "general"),
                        "title": insight.get("title", ""),
                        "body": insight.get("body", ""),
                        "data": json.dumps(insight),
                    })
                db.commit()
                return {"insights_created": len(insights_data)}
            finally:
                db.close()
    except Exception as e:
        logger.error(f"generate_user_insights({user_id}) failed: {e}")
        return {"error": str(e)}

@shared_task(name="app.workers.ai_tasks.recalculate_all_health_scores")
def recalculate_all_health_scores():
    """Recalculate health score for all users"""
    import httpx
    db = get_db_session()
    try:
        users = db.execute(text(
            "SELECT id FROM users WHERE is_active = true AND onboarding_done = true"
        )).fetchall()

        count = 0
        for user in users:
            try:
                r = httpx.get(f"http://localhost:8001/api/v1/health-score?user_id={user.id}", timeout=10)
                if r.status_code == 200:
                    score_data = r.json().get("data", {})
                    import uuid, json
                    db.execute(text("""
                        INSERT INTO financial_health_scores (id, user_id, score, breakdown, calculated_at)
                        VALUES (:id, :uid, :score, :breakdown::jsonb, NOW())
                    """), {
                        "id": str(uuid.uuid4()),
                        "uid": str(user.id),
                        "score": score_data.get("score", 50),
                        "breakdown": json.dumps(score_data.get("breakdown", {})),
                    })
                    count += 1
            except Exception as e:
                logger.warning(f"Health score failed for {user.id}: {e}")

        db.commit()
        return {"scores_updated": count}
    finally:
        db.close()

@shared_task(name="app.workers.ai_tasks.generate_ai_profile")
def generate_ai_profile(user_id: str):
    """Called after onboarding completes"""
    logger.info(f"Generating AI profile for user {user_id}")
    generate_user_insights.delay(user_id)
    return {"status": "profile_generation_queued", "user_id": user_id}
