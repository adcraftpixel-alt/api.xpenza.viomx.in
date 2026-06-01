from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "afos_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.notification_tasks",
        "app.workers.ai_tasks",
        "app.workers.report_tasks",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Scheduled tasks
celery_app.conf.beat_schedule = {
    # Budget alerts — every hour
    "check-budget-alerts": {
        "task": "app.workers.notification_tasks.check_budget_alerts",
        "schedule": crontab(minute=0),  # every hour
    },
    # Weekly summary — every Monday 9 AM IST
    "weekly-summary": {
        "task": "app.workers.notification_tasks.send_weekly_summaries",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
    # Monthly report — 1st of month 9 AM IST
    "monthly-report": {
        "task": "app.workers.notification_tasks.send_monthly_reports",
        "schedule": crontab(hour=9, minute=0, day_of_month=1),
    },
    # Subscription reminders — daily 10 AM IST
    "subscription-reminders": {
        "task": "app.workers.notification_tasks.send_subscription_reminders",
        "schedule": crontab(hour=10, minute=0),
    },
    # AI insights generation — nightly 2 AM IST
    "generate-insights": {
        "task": "app.workers.ai_tasks.generate_all_user_insights",
        "schedule": crontab(hour=2, minute=0),
    },
    # Health score recalculation — every Sunday 3 AM IST
    "recalculate-health-scores": {
        "task": "app.workers.ai_tasks.recalculate_all_health_scores",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),
    },
}
