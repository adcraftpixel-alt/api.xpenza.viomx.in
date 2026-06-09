import logging
from datetime import date, timedelta
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ai_insight import AIInsight
from app.models.expense import Expense
from app.models.budget import Budget
from app.models.savings_goal import SavingsGoal
from app.models.chat import AIChatHistory
from app.config import settings

logger = logging.getLogger(__name__)


def _call_ai_service(path: str, method: str = "GET", json: dict | None = None) -> dict | None:
    """Proxy to ai_services microservice. Returns None if unavailable."""
    try:
        import httpx
        url = f"{settings.AI_SERVICE_URL}{path}"
        with httpx.Client(timeout=10.0) as client:
            if method == "POST":
                resp = client.post(url, json=json)
            else:
                resp = client.get(url)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


class AIService:
    def get_insights(self, db: Session, user_id: str) -> List[dict]:
        # Try ai_services first for real-time insights
        result = _call_ai_service(f"/api/v1/insights?user_id={user_id}")
        if result and isinstance(result, list):
            return result

        insights = (
            db.query(AIInsight)
            .filter(AIInsight.user_id == user_id)
            .order_by(AIInsight.created_at.desc())
            .limit(20)
            .all()
        )
        if not insights:
            return [
                {
                    "id": "sample-1",
                    "type": "tip",
                    "title": "Track your first expense",
                    "body": "Start adding expenses to get personalized AI insights about your spending patterns.",
                    "data": None,
                    "is_read": False,
                }
            ]
        return [
            {
                "id": str(i.id),
                "type": i.type,
                "title": i.title,
                "body": i.body,
                "data": i.data,
                "is_read": i.is_read,
            }
            for i in insights
        ]

    def get_health_score(self, db: Session, user_id: str, user) -> dict:
        score = 50
        breakdown = {}
        recommendations = []

        # Budget adherence (0-30 points)
        budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).all()
        if budgets:
            within_budget = sum(
                1 for b in budgets if float(b.spent) <= float(b.amount)
            )
            budget_score = int((within_budget / len(budgets)) * 30)
            breakdown["budget_adherence"] = {"score": budget_score, "max": 30}
            score = budget_score
            if budget_score < 20:
                recommendations.append("Review your budget limits — you're overspending in some categories.")
        else:
            breakdown["budget_adherence"] = {"score": 0, "max": 30, "note": "No budgets set"}
            recommendations.append("Set up budgets to track spending effectively.")
            score = 20

        # Savings goals (0-20 points)
        goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id).all()
        if goals:
            active_goals = [g for g in goals if not g.is_completed]
            goals_score = min(20, len(active_goals) * 7)
            breakdown["savings_goals"] = {"score": goals_score, "max": 20, "active": len(active_goals)}
            score += goals_score
        else:
            breakdown["savings_goals"] = {"score": 0, "max": 20, "note": "No savings goals"}
            recommendations.append("Create a savings goal to improve your financial health.")

        # Expense consistency (0-25 points)
        from app.utils.period import current_period_window
        today = date.today()
        month_start, month_end = current_period_window(db, user_id, today)
        expenses_this_month = db.query(func.count(Expense.id)).filter(
            Expense.user_id == user_id,
            Expense.expense_date >= month_start,
            Expense.expense_date <= month_end,
        ).scalar() or 0
        consistency_score = min(25, expenses_this_month * 2)
        breakdown["expense_tracking"] = {"score": consistency_score, "max": 25, "expenses_this_month": expenses_this_month}
        score += consistency_score

        # Income tracking (0-25 points)
        income_score = 25 if user.monthly_income and float(user.monthly_income) > 0 else 0
        breakdown["income_set"] = {"score": income_score, "max": 25}
        score += income_score
        if not income_score:
            recommendations.append("Set your monthly income to unlock savings rate tracking.")

        score = min(100, score)
        grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "F"

        return {
            "score": score,
            "grade": grade,
            "breakdown": breakdown,
            "recommendations": recommendations,
        }

    def get_savings_advice(self, db: Session, user_id: str, user) -> List[dict]:
        from app.utils.period import current_period_window
        advice = []
        today = date.today()
        month_start, month_end = current_period_window(db, user_id, today)

        total_spent = float(
            db.query(func.sum(Expense.amount))
            .filter(
                Expense.user_id == user_id,
                Expense.expense_date >= month_start,
                Expense.expense_date <= month_end,
            )
            .scalar() or 0
        )

        if user.monthly_income:
            income = float(user.monthly_income)
            savings = income - total_spent
            if savings < 0:
                advice.append({
                    "type": "warning",
                    "title": "You're overspending this month",
                    "body": f"You've spent ₹{total_spent:,.0f} against income of ₹{income:,.0f}.",
                    "action": "Review and cut non-essential expenses",
                })
            elif savings / income < 0.2:
                advice.append({
                    "type": "suggestion",
                    "title": "Low savings rate",
                    "body": f"You're saving only {((savings/income)*100):.1f}% of your income. Aim for 20%+.",
                    "action": "Identify your top spending category and reduce by 10%",
                })
            else:
                advice.append({
                    "type": "positive",
                    "title": "Great savings rate!",
                    "body": f"You're saving {((savings/income)*100):.1f}% of your income this month.",
                    "action": "Consider investing the surplus",
                })

        advice.append({
            "type": "tip",
            "title": "50/30/20 Rule",
            "body": "Allocate 50% to needs, 30% to wants, and 20% to savings & investments.",
            "action": "Review your category spending breakdown",
        })
        return advice

    def get_predictions(self, db: Session, user_id: str) -> dict:
        """Simple moving average prediction over last 3 months."""
        today = date.today()
        monthly_totals = []
        monthly_data = []

        for i in range(1, 4):
            if today.month - i <= 0:
                m = today.month - i + 12
                y = today.year - 1
            else:
                m = today.month - i
                y = today.year
            month_start = today.replace(year=y, month=m, day=1)
            if m == 12:
                month_end = today.replace(year=y + 1, month=1, day=1)
            else:
                month_end = today.replace(year=y, month=m + 1, day=1)

            total = float(
                db.query(func.sum(Expense.amount))
                .filter(
                    Expense.user_id == user_id,
                    Expense.expense_date >= month_start,
                    Expense.expense_date < month_end,
                )
                .scalar() or 0
            )
            monthly_totals.append(total)
            monthly_data.append({"month": f"{y}-{m:02d}", "total": total})

        avg = sum(monthly_totals) / len(monthly_totals) if monthly_totals else 0
        trend = "stable"
        if len(monthly_totals) >= 2:
            if monthly_totals[0] > monthly_totals[1] * 1.1:
                trend = "increasing"
            elif monthly_totals[0] < monthly_totals[1] * 0.9:
                trend = "decreasing"

        return {
            "next_month_estimate": round(avg, 2),
            "trend": trend,
            "monthly_data": list(reversed(monthly_data)),
            "confidence": 0.7 if all(t > 0 for t in monthly_totals) else 0.3,
        }

    def chat(self, db: Session, user_id: str, message: str) -> dict:
        # Try ai_services microservice first (has OpenAI + context-aware responses)
        result = _call_ai_service("/api/v1/chat", method="POST", json={"user_id": user_id, "message": message})
        if result and result.get("text"):
            return result

        # Fallback: rule-based response + persist to DB
        user_msg = AIChatHistory(user_id=user_id, role="user", message=message)
        db.add(user_msg)

        msg_lower = message.lower()
        if any(w in msg_lower for w in ["spend", "spent", "expense", "cost"]):
            text = "Based on your recent expenses, I can see your spending patterns. Add more expenses for detailed AI analysis."
            suggestions = ["Show my top spending categories", "How can I reduce food expenses?"]
        elif any(w in msg_lower for w in ["save", "saving", "goal"]):
            text = "Setting savings goals is a great first step! Create a savings goal and I'll help you track your progress."
            suggestions = ["Create a savings goal", "What is a good savings rate?"]
        elif any(w in msg_lower for w in ["budget", "over budget"]):
            text = "Budgets help you stay on track. I recommend setting budgets for your top 3 spending categories."
            suggestions = ["Show my budgets", "Create a new budget"]
        else:
            text = "I'm your AI finance assistant. I can help you analyze expenses, optimize budgets, and reach your savings goals."
            suggestions = ["How much did I spend this month?", "Show my financial health score", "Give me savings tips"]

        ai_msg = AIChatHistory(user_id=user_id, role="assistant", message=text)
        db.add(ai_msg)
        db.commit()

        return {
            "text": text,
            "data_type": None,
            "data": None,
            "suggestions": suggestions,
        }

    def get_chat_history(self, db: Session, user_id: str, limit: int = 50) -> List[dict]:
        messages = (
            db.query(AIChatHistory)
            .filter(AIChatHistory.user_id == user_id)
            .order_by(AIChatHistory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {"id": str(m.id), "role": m.role, "message": m.message, "created_at": str(m.created_at)}
            for m in reversed(messages)
        ]
