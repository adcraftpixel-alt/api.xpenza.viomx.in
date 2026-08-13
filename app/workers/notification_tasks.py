from celery import shared_task
from sqlalchemy import text
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def get_db_session():
    from app.database import SessionLocal
    return SessionLocal()

@shared_task(name="app.workers.notification_tasks.check_budget_alerts")
def check_budget_alerts():
    """Check all active budgets and send alerts when threshold exceeded"""
    db = get_db_session()
    try:
        # Find budgets where spent >= alert_threshold% of amount
        budgets_at_risk = db.execute(text("""
            SELECT b.id, b.user_id, b.amount, b.spent, b.alert_threshold,
                   COALESCE(c.name, 'Budget') as category_name,
                   u.name as user_name,
                   (SELECT device_token FROM user_device_tokens
                    WHERE user_id = b.user_id LIMIT 1) as device_token
            FROM budgets b
            LEFT JOIN categories c ON c.id = b.category_id
            LEFT JOIN users u ON u.id = b.user_id
            WHERE b.is_active = true
              AND b.amount > 0
              AND (b.spent / b.amount * 100) >= b.alert_threshold
              AND NOT EXISTS (
                  SELECT 1 FROM notifications n
                  WHERE n.user_id = b.user_id
                    AND n.type = 'budget_alert'
                    AND n.data->>'budget_id' = b.id::text
                    AND n.created_at >= NOW() - INTERVAL '24 hours'
              )
        """)).fetchall()

        import uuid
        notifications_created = 0
        for budget in budgets_at_risk:
            pct = (float(budget.spent) / float(budget.amount)) * 100
            is_over = float(budget.spent) >= float(budget.amount)

            title = f"{'Over' if is_over else 'Near'} budget: {budget.category_name}"
            body = f"₹{budget.spent:,.0f} {'spent' if is_over else 'of ₹'}{'' if is_over else f'{budget.amount:,.0f}'} ({pct:.0f}%{'over!' if is_over else ' used'})"

            # Create notification record
            db.execute(text("""
                INSERT INTO notifications (id, user_id, title, body, type, is_read, data, created_at)
                VALUES (:id, :uid, :title, :body, 'budget_alert',
                        false, CAST(:data AS JSONB), NOW())
            """), {
                "id": str(uuid.uuid4()),
                "uid": str(budget.user_id),
                "title": title,
                "body": body,
                "data": f'{{"budget_id": "{budget.id}", "percentage": {pct:.1f}}}',
            })

            # Send push notification
            if budget.device_token:
                from app.utils.fcm import send_push_notification
                send_push_notification(
                    budget.device_token, title, body,
                    {"type": "budget_alert", "budget_id": str(budget.id)},
                    "budget_alert"
                )
            notifications_created += 1

        db.commit()
        logger.info(f"Budget alerts: {notifications_created} notifications sent")
        return {"notifications_sent": notifications_created}
    except Exception as e:
        logger.error(f"check_budget_alerts error: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@shared_task(name="app.workers.notification_tasks.send_subscription_reminders")
def send_subscription_reminders():
    """Remind users of subscriptions renewing in next 3 days"""
    db = get_db_session()
    try:
        upcoming = db.execute(text("""
            SELECT ts.user_id, ts.name, ts.amount, ts.next_renewal,
                   (SELECT device_token FROM user_device_tokens
                    WHERE user_id = ts.user_id LIMIT 1) as device_token
            FROM tracked_subscriptions ts
            WHERE ts.is_active = true
              AND ts.next_renewal IS NOT NULL
              AND ts.next_renewal BETWEEN NOW() AND NOW() + INTERVAL '3 days'
              AND NOT EXISTS (
                  SELECT 1 FROM notifications n
                  WHERE n.user_id = ts.user_id
                    AND n.type = 'subscription_renewal'
                    AND n.data->>'sub_name' = ts.name
                    AND n.created_at >= NOW() - INTERVAL '24 hours'
              )
        """)).fetchall()

        import uuid
        count = 0
        for sub in upcoming:
            days_left = (sub.next_renewal - datetime.utcnow().date()).days
            title = f"{sub.name} renews {'tomorrow' if days_left <= 1 else f'in {days_left} days'}"
            body = f"₹{sub.amount:,.0f} will be charged on {sub.next_renewal}"

            db.execute(text("""
                INSERT INTO notifications (id, user_id, title, body, type, is_read, data, created_at)
                VALUES (:id, :uid, :title, :body, 'subscription_renewal',
                        false, CAST(:data AS JSONB), NOW())
            """), {
                "id": str(uuid.uuid4()),
                "uid": str(sub.user_id),
                "title": title, "body": body,
                "data": f'{{"sub_name": "{sub.name}", "amount": {sub.amount}}}',
            })

            if sub.device_token:
                from app.utils.fcm import send_push_notification
                send_push_notification(sub.device_token, title, body, notification_type="subscription_renewal")
            count += 1

        db.commit()
        logger.info(f"Subscription reminders: {count} sent")
        return {"sent": count}
    except Exception as e:
        logger.error(f"send_subscription_reminders error: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@shared_task(name="app.workers.notification_tasks.send_weekly_summaries")
def send_weekly_summaries():
    """Send weekly spending summary to all users"""
    db = get_db_session()
    try:
        week_ago = datetime.utcnow() - timedelta(days=7)
        users = db.execute(text("""
            SELECT u.id, u.name,
                   COALESCE(SUM(e.amount), 0) as week_total,
                   COUNT(e.id) as txn_count,
                   (SELECT device_token FROM user_device_tokens
                    WHERE user_id = u.id LIMIT 1) as device_token
            FROM users u
            LEFT JOIN expenses e ON e.user_id = u.id AND e.expense_date >= :week_ago
            WHERE u.is_active = true AND u.onboarding_done = true
            GROUP BY u.id, u.name
        """), {"week_ago": week_ago}).fetchall()

        import uuid
        count = 0
        for user in users:
            if float(user.week_total) == 0:
                continue
            title = "Your weekly spending summary"
            body = f"You spent ₹{user.week_total:,.0f} across {user.txn_count} transactions this week"

            db.execute(text("""
                INSERT INTO notifications (id, user_id, title, body, type, created_at)
                VALUES (:id, :uid, :title, :body, 'weekly_summary', NOW())
            """), {"id": str(uuid.uuid4()), "uid": str(user.id), "title": title, "body": body})

            if user.device_token:
                from app.utils.fcm import send_push_notification
                send_push_notification(user.device_token, title, body, notification_type="weekly_summary")
            count += 1

        db.commit()
        return {"weekly_summaries_sent": count}
    except Exception as e:
        logger.error(f"send_weekly_summaries error: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@shared_task(name="app.workers.notification_tasks.send_monthly_reports")
def send_monthly_reports():
    """Send monthly expense report notification"""
    db = get_db_session()
    try:
        from datetime import date
        from calendar import monthrange
        now = datetime.utcnow()
        prev_month = (now.replace(day=1) - timedelta(days=1))
        _, days = monthrange(prev_month.year, prev_month.month)
        start = date(prev_month.year, prev_month.month, 1)
        end = date(prev_month.year, prev_month.month, days)

        users = db.execute(text("""
            SELECT u.id, u.name,
                   COALESCE(SUM(e.amount), 0) as month_total,
                   (SELECT device_token FROM user_device_tokens
                    WHERE user_id = u.id LIMIT 1) as device_token
            FROM users u
            LEFT JOIN expenses e ON e.user_id = u.id
                AND e.expense_date >= :start AND e.expense_date <= :end
            WHERE u.is_active = true AND u.onboarding_done = true
            GROUP BY u.id, u.name
        """), {"start": start, "end": end}).fetchall()

        import uuid
        count = 0
        month_name = prev_month.strftime("%B")
        for user in users:
            title = f"Your {month_name} report is ready"
            body = f"Total spent in {month_name}: ₹{user.month_total:,.0f}. Tap to view full report."

            db.execute(text("""
                INSERT INTO notifications (id, user_id, title, body, type, created_at)
                VALUES (:id, :uid, :title, :body, 'monthly_report', NOW())
            """), {"id": str(uuid.uuid4()), "uid": str(user.id), "title": title, "body": body})

            if user.device_token:
                from app.utils.fcm import send_push_notification
                send_push_notification(user.device_token, title, body, notification_type="monthly_report")
            count += 1

        db.commit()
        return {"monthly_reports_sent": count}
    except Exception as e:
        logger.error(f"send_monthly_reports error: {e}")
        return {"error": str(e)}
    finally:
        db.close()
