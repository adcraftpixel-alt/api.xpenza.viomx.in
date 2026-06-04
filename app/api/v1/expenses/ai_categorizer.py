"""
Multilingual AI expense categorizer.

Takes an expense description in ANY language (Hindi, Punjabi, Hinglish,
English, etc.) and matches it to the user's own custom category tree using
the Groq LLM.  Falls back to a keyword/regex approach when the API is
unavailable so the feature degrades gracefully.
"""

import json
import os
import re
import logging
import httpx
from sqlalchemy.orm import Session

from app.models.category import Category

logger = logging.getLogger(__name__)

_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_GROQ_MODEL   = "llama-3.1-8b-instant"

# Common Hindi/Punjabi → English concept mappings used by the regex fallback
_HINDI_KEYWORDS: list[tuple[str, str]] = [
    (r'doodh|dudh|milk',                          'milk groceries'),
    (r'chai|tea|coffee',                           'tea food dining'),
    (r'khana|khaana|roti|sabzi|chawal|khane',      'food dining restaurant'),
    (r'nashta|nasta|breakfast',                    'breakfast food'),
    (r'petrol|diesel|fuel|tanki',                  'petrol fuel transport'),
    (r'dawai|dawa|medicine|tablet|doctor|hospital','medicine health medical'),
    (r'kiraya|kira|rent|makaan|flat|pg',           'rent house emi'),
    (r'bijli|light bill|electricity',              'electricity bill utilities'),
    (r'paani|water',                               'water bill utilities'),
    (r'gas|cylinder|lpg',                          'gas cylinder utilities'),
    (r'kapde|kapdey|kurta|shirt|pant|jeans',       'clothes shopping fashion'),
    (r'school|padhai|fees|tuition|kitab|book',     'education school fees'),
    (r'ghar|home|maintenance',                     'home house maintenance'),
    (r'sip|invest|mutual fund|fd|insurance',       'investment sip mutual fund'),
    (r'salon|haircut|baal|parlour|parlor',         'salon haircut personal care'),
    (r'sabzi|mandi|vegetable|fruit|aachar',        'vegetable grocery'),
    (r'auto|rickshaw|bus|metro|train|uber|ola|cab','transport travel'),
    (r'movie|cinema|netflix|hotstar|prime|show',   'entertainment movie'),
    (r'recharge|sim|mobile|wifi|internet|jio|airtel','recharge bill utilities'),
]


def _build_category_tree(db: Session, user_id: str) -> list[dict]:
    """Return user's full category tree (root → children → grandchildren)."""
    roots = (
        db.query(Category)
        .filter(Category.user_id == user_id, Category.parent_id.is_(None))
        .all()
    )
    result = []
    for cat in roots:
        entry: dict = {"id": str(cat.id), "name": cat.name, "subcategories": []}
        for child in (cat.children or []):
            sub: dict = {"id": str(child.id), "name": child.name, "subcategories": []}
            for grandchild in (child.children or []):
                sub["subcategories"].append(
                    {"id": str(grandchild.id), "name": grandchild.name}
                )
            entry["subcategories"].append(sub)
        result.append(entry)
    return result


def suggest_category(description: str, user_id: str, db: Session) -> dict:
    """
    Match an expense description (any language) to the user's custom categories.

    Returns:
        {
          "category_id":      str | None,
          "category_name":    str,
          "subcategory_id":   str | None,
          "subcategory_name": str | None,
        }
    """
    categories = _build_category_tree(db, user_id)
    if not categories:
        return _empty()

    if _GROQ_API_KEY:
        result = _groq_suggest(description, categories)
        if result:
            return result

    return _regex_fallback(description, categories)


# ── Groq LLM ─────────────────────────────────────────────────────────────────

def _groq_suggest(description: str, categories: list[dict]) -> dict | None:
    prompt = f"""You are a multilingual expense categorizer for an Indian personal finance app.

Expense description (may be in Hindi, Punjabi, Hinglish, English, or any mix):
"{description}"

User's category tree (JSON):
{json.dumps(categories, ensure_ascii=False)}

Your job:
- Understand the description in any language. Examples:
    "doodh liya" → milk → match to Groceries-type category
    "chai peeni thi" → tea → match to Food/Dining-type category
    "bijli ka bill" → electricity → match to Bills/Utilities-type category
    "doctor ke paas gaya" → doctor → match to Health-type category
    "petrol dala" → petrol → match to Transport/Fuel-type category
    "kapde liye Amazon se" → clothes online → match to Shopping-type category
    "kiraya diya" → rent → match to Rent/EMI-type category
    "SIP kategi" → investment → match to Investments-type category
- ALWAYS pick from the user's list above — never invent a category.
- Prefer the most specific match (subcategory > root category).
- If unsure, pick the closest root category.

Respond with ONLY this JSON (no markdown, no extra text):
{{"category_id":"<uuid>","category_name":"<name>","subcategory_id":<uuid or null>,"subcategory_name":<name or null>}}"""

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {_GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 120,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if the model added them
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        cat_id   = data.get("category_id")
        cat_name = data.get("category_name", "General")
        sub_id   = data.get("subcategory_id")
        sub_name = data.get("subcategory_name")

        # Validate returned IDs exist in the tree
        valid_ids = {
            c["id"] for c in categories
        } | {
            s["id"] for c in categories for s in c.get("subcategories", [])
        } | {
            g["id"] for c in categories
            for s in c.get("subcategories", [])
            for g in s.get("subcategories", [])
        }
        if cat_id and cat_id not in valid_ids:
            cat_id = None
        if sub_id and sub_id not in valid_ids:
            sub_id   = None
            sub_name = None

        return {
            "category_id":      cat_id,
            "category_name":    cat_name,
            "subcategory_id":   sub_id,
            "subcategory_name": sub_name,
        }

    except Exception as exc:
        logger.warning("Groq category suggestion failed: %s", exc)
        return None


# ── Regex / keyword fallback ──────────────────────────────────────────────────

def _regex_fallback(description: str, categories: list[dict]) -> dict:
    """
    Expand Hindi/Punjabi keywords to English equivalents, then score each
    category by how many words from its name appear in the expanded description.
    """
    desc = description.lower()

    # Expand to English concepts
    expanded = desc
    for pattern, english in _HINDI_KEYWORDS:
        if re.search(pattern, desc, re.IGNORECASE):
            expanded += " " + english

    best_cat   = None
    best_sub   = None
    best_score = 0

    for cat in categories:
        # Score root category
        cat_words = set(re.findall(r'\w+', cat["name"].lower()))
        score = sum(1 for w in cat_words if w in expanded)

        # Score subcategories
        for sub in cat.get("subcategories", []):
            sub_words = set(re.findall(r'\w+', sub["name"].lower()))
            sub_score = score + sum(1 for w in sub_words if w in expanded)
            if sub_score > best_score:
                best_score = sub_score
                best_cat   = cat
                best_sub   = sub

        if score > best_score and best_sub is None:
            best_score = score
            best_cat   = cat

    if best_cat:
        return {
            "category_id":      best_cat["id"],
            "category_name":    best_cat["name"],
            "subcategory_id":   best_sub["id"]   if best_sub else None,
            "subcategory_name": best_sub["name"] if best_sub else None,
        }

    # Last resort: return first root category
    first = categories[0]
    return {
        "category_id":      first["id"],
        "category_name":    first["name"],
        "subcategory_id":   None,
        "subcategory_name": None,
    }


def _empty() -> dict:
    return {
        "category_id":      None,
        "category_name":    "General",
        "subcategory_id":   None,
        "subcategory_name": None,
    }
