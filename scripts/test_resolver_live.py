"""
END-TO-END test of the real categorizer against the LIVE database + Groq LLM.

Calls the actual app.api.v1.expenses.ai_categorizer.suggest_category() using a
real user's seeded category tree from the configured DATABASE_URL. READ-ONLY —
suggest_category() only queries; nothing is written.

Shows method=[keyword|llm|fallback] so you can see which layer resolved each.

Run:  .venv/bin/python scripts/test_resolver_live.py
"""
from app.database import SessionLocal
from app.models.category import Category
from app.api.v1.expenses.ai_categorizer import suggest_category, _GROQ_API_KEY

ENTRIES = [
    # keyword layer (already seeded)
    "Milk", "Doodh", "Petrol", "Uber", "Bijli ka bill", "Kiraya",
    "Netflix", "Zomato order", "Kapde", "Sona", "Tea", "Sabzi",
    # LLM layer (no seeded keyword in live DB -> exercises Groq)
    "Paracetamol", "Crocin tablet", "X-ray", "iPhone 15", "Dolo 650",
    "Haldiram namkeen", "Burger", "Water bottle", "Cigarette",
]


def main():
    db = SessionLocal()
    try:
        # Pick a user that actually has a personal category tree seeded.
        row = (
            db.query(Category.user_id)
            .filter(Category.parent_id.is_(None), Category.family_group_id.is_(None))
            .first()
        )
        if not row:
            print("No seeded personal categories found in the DB.")
            return
        user_id = str(row[0])

        n_cats = (
            db.query(Category)
            .filter(Category.user_id == user_id, Category.family_group_id.is_(None))
            .count()
        )
        print(f"Live DB | user {user_id[:8]}… has {n_cats} category nodes | "
              f"Groq key: {'set' if _GROQ_API_KEY else 'MISSING'}")
        print("-" * 70)
        print(f"{'ENTRY':<20} {'METHOD':<9} RESOLVES TO")
        print("-" * 70)

        for e in ENTRIES:
            r = suggest_category(e, user_id, db)
            path = " › ".join(r.get("path") or []) or r.get("category_name")
            print(f"{e:<20} {r.get('method'):<9} {path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
