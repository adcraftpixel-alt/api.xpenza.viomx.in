"""Validate the Groq key + model + categorization prompt end-to-end.

Replicates app/api/v1/expenses/ai_categorizer.py::_groq_suggest with a small
fake category tree and checks the previously-unmatched entries now resolve.
"""
import json
import os
import re
import sys
import httpx

# Read key from .env (no dotenv loader in the app for scripts)
KEY = ""
with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        if line.startswith("GROQ_API_KEY="):
            KEY = line.split("=", 1)[1].strip()
MODEL = "llama-3.3-70b-versatile"

# Minimal tree (fake ids) covering the relevant branches. Uses the same
# "subcategories" key the production tree builder emits.
TREE = [
    {"id": "g", "name": "Groceries", "subcategories": [
        {"id": "g-snack", "name": "Snacks & Packaged", "subcategories": []}]},
    {"id": "food", "name": "Food & Dining", "subcategories": [
        {"id": "food-rest", "name": "Restaurant", "subcategories": []},
        {"id": "food-street", "name": "Street Food & Snacks", "subcategories": []}]},
    {"id": "shop", "name": "Shopping", "subcategories": [
        {"id": "shop-elec", "name": "Electronics", "subcategories": []}]},
    {"id": "health", "name": "Health & Medical", "subcategories": [
        {"id": "health-med", "name": "Medicine", "subcategories": []},
        {"id": "health-lab", "name": "Tests & Lab", "subcategories": []}]},
    {"id": "gen", "name": "General", "subcategories": []},
]
NAME = {n["id"]: n["name"] for r in TREE for n in [r] + r["subcategories"]}


def groq_suggest(description: str):
    prompt = f"""You are a multilingual expense categorizer for an Indian personal finance app.

Expense description (may be Hindi, Punjabi, Hinglish, English, or any mix):
"{description}"

User's category tree (JSON):
{json.dumps(TREE, ensure_ascii=False)}

Rules:
- Understand the description in any language.
- ALWAYS pick ids from the tree above — never invent one.
- Prefer the MOST SPECIFIC match: grandchild > child > root.

Respond with ONLY this JSON (no markdown):
{{"category_id":"<root uuid>","subcategory_id":<child or grandchild uuid or null>}}"""
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"model": MODEL, "temperature": 0, "max_tokens": 120,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=15.0,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    # Same robust extraction as the production fix.
    m = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    obj = json.loads(m.group(0))
    node = obj.get("subcategory_id") or obj.get("category_id")
    return NAME.get(node, f"?{node}")


if __name__ == "__main__":
    if not KEY:
        print("NO GROQ_API_KEY in .env"); sys.exit(1)
    tests = ["Paracetamol", "Crocin tablet", "X-ray", "iPhone 15",
             "Haldiram namkeen", "Cigarette", "Dolo 650", "Burger"]
    print(f"Model: {MODEL}\n" + "-" * 50)
    for t in tests:
        try:
            print(f"{t:<20} -> {groq_suggest(t)}")
        except Exception as e:
            print(f"{t:<20} -> ERROR: {type(e).__name__}: {e}")
