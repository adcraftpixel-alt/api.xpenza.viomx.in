"""
Seed script — populates the DB with realistic Indian finance dummy data.
Run: cd backend && .venv/bin/python seed_demo.py
"""
import uuid
import random
from datetime import datetime, date, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.category import Category
from app.models.expense import Expense
from app.models.budget import Budget
from app.models.savings_goal import SavingsGoal
from app.models.notification import Notification
from app.models.ai_insight import AIInsight
from app.models.subscription import TrackedSubscription

db = SessionLocal()

# ── 1. Demo user ────────────────────────────────────────────────────────────
EMAIL = "demo@rupexi.com"
existing = db.query(User).filter(User.email == EMAIL).first()
if existing:
    user = existing
    print(f"Using existing demo user: {user.email}")
else:
    user = User(
        id=uuid.uuid4(),
        name="Arjun Sharma",
        email=EMAIL,
        password_hash=hash_password("Demo@1234"),
        user_type="personal",
        monthly_income=85000.00,
        currency="INR",
        is_verified=True,
        is_active=True,
        onboarding_done=True,
    )
    db.add(user)
    db.flush()
    db.add(UserPreference(
        id=uuid.uuid4(),
        user_id=user.id,
        notification_frequency="daily",
        ai_insights_enabled=True,
        ai_savings_enabled=True,
        ai_budget_prediction=True,
        theme="light",
    ))
    print(f"Created demo user: {user.email}")

uid = user.id

# ── 2. Categories ────────────────────────────────────────────────────────────
cat_defs = [
    ("Food & Dining",    "restaurant",   "#FF7043", True),
    ("Transport",        "directions_car","#42A5F5", True),
    ("Shopping",         "shopping_bag", "#AB47BC", True),
    ("Bills & Utilities","receipt_long", "#FFA726", True),
    ("Health",           "medical_services","#EF5350", True),
    ("Entertainment",    "movie",        "#26C6DA", True),
    ("Groceries",        "local_grocery_store","#66BB6A", True),
    ("Education",        "school",       "#7E57C2", True),
    ("Travel",           "flight",       "#26A69A", True),
    ("Personal Care",    "spa",          "#EC407A", True),
]

cats = {}
for name, icon, color, is_default in cat_defs:
    existing_cat = db.query(Category).filter(
        Category.user_id == uid, Category.name == name
    ).first()
    if existing_cat:
        cats[name] = existing_cat
    else:
        c = Category(id=uuid.uuid4(), user_id=uid, name=name, icon=icon,
                     color=color, is_default=is_default)
        db.add(c)
        cats[name] = c

db.flush()
print(f"Categories: {len(cats)}")

# ── 3. Expenses (90 days, realistic Indian spends) ───────────────────────────
today = date.today()

expense_templates = [
    # (category, description, min, max, freq_per_month, payment_method)
    ("Food & Dining",     "Swiggy order",          180, 450,  10, "upi"),
    ("Food & Dining",     "Zomato delivery",        200, 500,   8, "upi"),
    ("Food & Dining",     "Restaurant dinner",      600, 2000,  4, "credit_card"),
    ("Food & Dining",     "Office canteen",          80, 150,  20, "cash"),
    ("Food & Dining",     "Tea & snacks",            30,  80,  25, "cash"),
    ("Transport",         "Ola cab",                120, 350,   8, "upi"),
    ("Transport",         "Uber ride",              150, 400,   6, "upi"),
    ("Transport",         "Metro card recharge",    200, 500,   2, "upi"),
    ("Transport",         "Petrol",                2000, 3500,  2, "credit_card"),
    ("Shopping",          "Amazon order",           500, 3000,  3, "credit_card"),
    ("Shopping",          "Myntra clothes",        1200, 4500,  2, "credit_card"),
    ("Shopping",          "Flipkart purchase",      800, 5000,  2, "upi"),
    ("Bills & Utilities", "Electricity bill",      1800, 2800,  1, "upi"),
    ("Bills & Utilities", "Broadband bill",         699, 899,   1, "upi"),
    ("Bills & Utilities", "Mobile recharge",        299, 599,   1, "upi"),
    ("Bills & Utilities", "Gas cylinder",           900, 1100,  1, "cash"),
    ("Health",            "Pharmacy",               200, 800,   2, "cash"),
    ("Health",            "Doctor consultation",    500, 1500,  1, "upi"),
    ("Health",            "Gym membership",         999, 1500,  1, "upi"),
    ("Entertainment",     "Netflix subscription",   649, 649,   1, "credit_card"),
    ("Entertainment",     "Movie tickets",          350, 900,   2, "upi"),
    ("Entertainment",     "Spotify Premium",        119, 119,   1, "credit_card"),
    ("Groceries",         "BigBasket order",        800, 2500,  4, "upi"),
    ("Groceries",         "Local market",           300, 700,   4, "cash"),
    ("Groceries",         "DMart shopping",        1200, 3000,  2, "debit_card"),
    ("Education",         "Udemy course",           399, 1299,  1, "credit_card"),
    ("Travel",            "Weekend trip",          3000, 8000,  1, "credit_card"),
    ("Personal Care",     "Haircut",                200, 500,   1, "cash"),
    ("Personal Care",     "Salon visit",            600, 1500,  1, "upi"),
]

# Generate 90 days of expenses
existing_expense_count = db.query(Expense).filter(Expense.user_id == uid).count()
if existing_expense_count < 10:
    expenses_added = 0
    for days_back in range(90, 0, -1):
        exp_date = today - timedelta(days=days_back)
        # each day pick 0-4 expense templates probabilistically
        for tmpl in expense_templates:
            cat_name, desc, min_amt, max_amt, freq, payment = tmpl
            # probability = freq/30 per day
            if random.random() < (freq / 30.0):
                amount = round(random.uniform(min_amt, max_amt), 2)
                e = Expense(
                    id=uuid.uuid4(),
                    user_id=uid,
                    category_id=cats[cat_name].id,
                    amount=Decimal(str(amount)),
                    currency="INR",
                    description=desc,
                    payment_method=payment,
                    expense_date=exp_date,
                    source="manual",
                    notes=None,
                )
                db.add(e)
                expenses_added += 1
    db.flush()
    print(f"Added {expenses_added} expenses")
else:
    print(f"Expenses already exist ({existing_expense_count}), skipping")

# ── 4. Budgets ───────────────────────────────────────────────────────────────
budget_defs = [
    ("Food & Dining",     "Food Budget",      8000,  6500),
    ("Transport",         "Transport Budget", 4000,  2800),
    ("Shopping",          "Shopping Budget",  6000,  7200),  # over budget!
    ("Bills & Utilities", "Bills Budget",     5500,  4200),
    ("Health",            "Health Budget",    3000,  1800),
    ("Entertainment",     "Fun Money",        2000,  1650),
    ("Groceries",         "Groceries Budget", 6000,  4900),
]

existing_budgets = db.query(Budget).filter(Budget.user_id == uid).count()
if existing_budgets < 3:
    month_start = today.replace(day=1)
    for cat_name, bname, amount, spent in budget_defs:
        b = Budget(
            id=uuid.uuid4(),
            user_id=uid,
            category_id=cats[cat_name].id,
            name=bname,
            amount=Decimal(str(amount)),
            spent=Decimal(str(spent)),
            period="monthly",
            start_date=month_start,
            alert_threshold=80.0,
            is_active=True,
        )
        db.add(b)
    db.flush()
    print(f"Added {len(budget_defs)} budgets")
else:
    print(f"Budgets already exist ({existing_budgets}), skipping")

# ── 5. Savings Goals ─────────────────────────────────────────────────────────
goal_defs = [
    ("Emergency Fund",       300000, 124000, date(2026, 12, 31)),
    ("New MacBook",           120000,  45000, date(2026, 9, 30)),
    ("Goa Trip 2026",          35000,  22000, date(2026, 8, 15)),
    ("Home Down Payment",    1000000, 180000, date(2028, 3, 31)),
    ("Wedding Fund",          500000,  75000, date(2027, 2, 14)),
]

existing_goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == uid).count()
if existing_goals < 3:
    for name, target, current, target_date in goal_defs:
        g = SavingsGoal(
            id=uuid.uuid4(),
            user_id=uid,
            name=name,
            target_amount=Decimal(str(target)),
            current_amount=Decimal(str(current)),
            target_date=target_date,
            is_completed=False,
        )
        db.add(g)
    db.flush()
    print(f"Added {len(goal_defs)} savings goals")
else:
    print(f"Goals already exist ({existing_goals}), skipping")

# ── 6. Tracked Subscriptions ─────────────────────────────────────────────────
sub_defs = [
    ("Netflix",     649,  "monthly", today + timedelta(days=8)),
    ("Spotify",     119,  "monthly", today + timedelta(days=12)),
    ("Amazon Prime",1499, "yearly",  today + timedelta(days=45)),
    ("Hotstar",     299,  "monthly", today + timedelta(days=3)),
    ("Gym",         1200, "monthly", today + timedelta(days=18)),
    ("iCloud 50GB", 75,   "monthly", today + timedelta(days=22)),
    ("Zerodha",     0,    "monthly", today + timedelta(days=30)),
]

existing_subs = db.query(TrackedSubscription).filter(TrackedSubscription.user_id == uid).count()
if existing_subs < 3:
    for name, amount, cycle, renewal in sub_defs:
        s = TrackedSubscription(
            id=uuid.uuid4(),
            user_id=uid,
            name=name,
            amount=Decimal(str(amount)),
            billing_cycle=cycle,
            next_renewal=renewal,
            category="Entertainment" if name in ("Netflix","Hotstar","Spotify","Amazon Prime") else "Health",
            is_active=True,
            detected_by_ai=name in ("Netflix", "Spotify", "Amazon Prime"),
        )
        db.add(s)
    db.flush()
    print(f"Added {len(sub_defs)} subscriptions")
else:
    print(f"Subscriptions already exist ({existing_subs}), skipping")

# ── 7. Notifications ─────────────────────────────────────────────────────────
notif_defs = [
    ("Budget Alert 🔴", "Your Shopping budget is 120% used this month. Consider reviewing your spend.", "budget_alert", today),
    ("Budget Warning ⚠️", "You've used 81% of your Food & Dining budget.", "budget_alert", today - timedelta(days=1)),
    ("Subscription Renewal 📅", "Hotstar Premium renews in 3 days for ₹299.", "subscription", today),
    ("AI Insight 💡", "You spent ₹3,200 more on Food this month vs last month.", "savings", today - timedelta(days=2)),
    ("Savings Milestone 🎉", "You've saved ₹45,000 towards your MacBook goal! 37.5% there.", "savings", today - timedelta(days=3)),
    ("Weekly Summary 📊", "This week: ₹4,820 spent across 23 transactions.", "system", today - timedelta(days=4)),
    ("AI Tip 🤖", "Switching to home-cooked meals 3x/week could save ₹1,800/month.", "savings", today - timedelta(days=5)),
]

existing_notifs = db.query(Notification).filter(Notification.user_id == uid).count()
if existing_notifs < 3:
    for title, body, ntype, created in notif_defs:
        n = Notification(
            id=uuid.uuid4(),
            user_id=uid,
            title=title,
            body=body,
            type=ntype,
            is_read=False,
            created_at=datetime.combine(created, datetime.min.time()),
        )
        db.add(n)
    db.flush()
    print(f"Added {len(notif_defs)} notifications")
else:
    print(f"Notifications already exist ({existing_notifs}), skipping")

# ── 8. AI Insights ───────────────────────────────────────────────────────────
insight_defs = [
    ("overspending", "Shopping Over Budget",
     "You've exceeded your shopping budget by ₹1,200 this month. Top overspend: Amazon (₹4,200) and Myntra (₹3,800).",
     {"severity": "high", "excess": 1200}),
    ("savings", "Save ₹2,400/month on Food",
     "You spend an average of ₹480/day on food. Reducing Swiggy/Zomato orders by 5 per month could save ₹2,400.",
     {"potential_saving": 2400, "action": "reduce_delivery"}),
    ("prediction", "Next Month Forecast",
     "Based on your spending patterns, you're predicted to spend ₹42,500 next month — 8% higher than this month.",
     {"predicted_amount": 42500, "confidence": 87, "trend": "increasing"}),
    ("health", "Financial Health Score: 72",
     "Your score improved by 5 points! Strong savings rate but high discretionary spending is pulling it down.",
     {"score": 72, "prev_score": 67, "grade": "B"}),
    ("subscription", "Subscription Audit",
     "You're spending ₹2,761/month on subscriptions. Hotstar and one other may be underused.",
     {"total_monthly": 2761, "at_risk_count": 2}),
]

existing_insights = db.query(AIInsight).filter(AIInsight.user_id == uid).count()
if existing_insights < 3:
    for itype, title, body, data in insight_defs:
        i = AIInsight(
            id=uuid.uuid4(),
            user_id=uid,
            type=itype,
            title=title,
            body=body,
            data=data,
            is_read=False,
            created_at=datetime.utcnow(),
        )
        db.add(i)
    db.flush()
    print(f"Added {len(insight_defs)} AI insights")
else:
    print(f"AI insights already exist ({existing_insights}), skipping")

# ── Commit ───────────────────────────────────────────────────────────────────
db.commit()
db.close()

print("\n✅ Seed complete!")
print(f"   Email:    demo@rupexi.com")
print(f"   Password: Demo@1234")
