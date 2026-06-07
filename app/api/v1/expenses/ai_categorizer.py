"""
Hybrid expense categorizer.

Resolves a typed item name (any language) to the deepest matching node in the
user's — or a family group's — real category tree:

    1. DB keyword match   — fast, offline, free. Matches the description against
                            `category_keywords` and returns the DEEPEST node
                            (e.g. "milk"/"doodh" → Groceries › Dairy Product › Milk).
    2. Groq LLM fallback  — only when no keyword matches. Matches against the tree.
    3. General fallback    — the scope's "General" category (matched=False) so the
                            UI can ask the user to pick.

User corrections feed back via `learn_keyword()`, so matching improves over time.

Scope:
    - Personal:  family_group_id=None  → categories where user_id=uid AND family_group_id IS NULL
    - Family:    family_group_id set    → categories where family_group_id=gid
"""

import json
import os
import re
import logging
import httpx
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.category import Category
from app.models.category_keyword import CategoryKeyword

logger = logging.getLogger(__name__)

# Read via settings so the key is picked up from .env (pydantic) AND real env
# vars in production — os.getenv alone misses the .env file (no dotenv loader).
_GROQ_API_KEY = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
# 70b-versatile is far more accurate at this task than 8b-instant (which often
# returned "General" for obvious items and even echoed the prompt placeholder).
_GROQ_MODEL   = "llama-3.3-70b-versatile"


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _tokens(s: str) -> set[str]:
    s = (s or "").lower()
    toks = set(re.findall(r"\w+", s))
    # Hyphen/slash-joined terms also match their concatenated form so a typed
    # "x-ray" hits the "xray" keyword and "t-shirt" hits "tshirt".
    for w in re.findall(r"\w[\w\-/]*\w", s):
        if "-" in w or "/" in w:
            toks.add(re.sub(r"[-/]", "", w))
    return toks


def _scope_filter(user_id: str, family_group_id: str | None):
    if family_group_id:
        return Category.family_group_id == family_group_id
    return and_(Category.user_id == user_id, Category.family_group_id.is_(None))


def _empty() -> dict:
    return {
        "category_id":      None,
        "category_name":    "General",
        "subcategory_id":   None,
        "subcategory_name": None,
        "path":             [],
        "path_ids":         [],
        "matched":          False,
        "method":           "none",
    }


def _build_result(db: Session, node_id: str, method: str, matched: bool) -> dict:
    """
    Given the resolved (deepest) node, walk up to the root to build the full
    path and the standard category/subcategory fields.

    `category_id` is the DEEPEST node — the expense links here. `path` is the
    human-readable trail (e.g. ["Groceries", "Dairy Product", "Milk"]).
    """
    node = db.query(Category).filter(Category.id == node_id).first()
    if not node:
        return _empty()

    # Walk root → ... → node
    chain: list[Category] = []
    cur = node
    seen = set()
    while cur is not None and str(cur.id) not in seen:
        chain.append(cur)
        seen.add(str(cur.id))
        cur = (
            db.query(Category).filter(Category.id == cur.parent_id).first()
            if cur.parent_id else None
        )
    chain.reverse()  # root first

    root = chain[0]
    sub  = chain[1] if len(chain) > 1 else None

    return {
        "category_id":      str(node.id),       # deepest node — expense links here
        "category_name":    node.name,
        "root_id":          str(root.id),
        "root_name":        root.name,
        "subcategory_id":   str(sub.id) if sub else None,
        "subcategory_name": sub.name if sub else None,
        "path":             [c.name for c in chain],
        "path_ids":         [str(c.id) for c in chain],
        "icon":             node.icon,
        "color":            node.color,
        "matched":          matched,
        "method":           method,
    }


# ── public API ──────────────────────────────────────────────────────────────

def suggest_category(
    description: str,
    user_id: str,
    db: Session,
    family_group_id: str | None = None,
) -> dict:
    """Resolve a description to the deepest matching category node in scope."""
    desc = _norm(description)
    if not desc:
        return _empty()

    # 1) DB keyword match (fast, offline)
    node_id = _keyword_match(db, desc, user_id, family_group_id)
    if node_id:
        return _build_result(db, node_id, method="keyword", matched=True)

    # 2) LLM fallback (only if a key is configured and a tree exists)
    if _GROQ_API_KEY:
        tree = _build_category_tree(db, user_id, family_group_id)
        if tree:
            node_id = _groq_suggest(desc, tree)
            if node_id:
                return _build_result(db, node_id, method="llm", matched=True)

    # 3) General fallback
    general = (
        db.query(Category)
        .filter(_scope_filter(user_id, family_group_id), Category.name == "General")
        .first()
    )
    if general:
        return _build_result(db, str(general.id), method="fallback", matched=False)

    return _empty()


def learn_keyword(
    db: Session,
    description: str,
    category_id: str,
    user_id: str,
    family_group_id: str | None = None,
) -> bool:
    """
    Persist a user's correction as a keyword alias so the same item resolves
    instantly next time. Validates the target category is in the caller's scope.
    Returns True if a new alias was stored.
    """
    kw = _norm(description)
    if not kw or len(kw) > 100:
        return False

    target = (
        db.query(Category)
        .filter(_scope_filter(user_id, family_group_id), Category.id == category_id)
        .first()
    )
    if not target:
        return False

    exists = (
        db.query(CategoryKeyword)
        .filter(
            CategoryKeyword.category_id == category_id,
            CategoryKeyword.keyword == kw,
        )
        .first()
    )
    if exists:
        return False

    db.add(CategoryKeyword(category_id=category_id, keyword=kw, source="learned"))
    db.commit()
    return True


# ── 1. keyword matcher ────────────────────────────────────────────────────────

def _keyword_match(
    db: Session, desc: str, user_id: str, family_group_id: str | None
) -> str | None:
    """
    Return the id of the deepest category whose keyword matches `desc`.

    Single-word keywords match on word boundaries (token set); multi-word
    keywords match as a phrase (substring). Ties broken by node depth, then
    by keyword length (more specific wins).
    """
    rows = (
        db.query(
            CategoryKeyword.keyword,
            CategoryKeyword.category_id,
            Category.level,
        )
        .join(Category, Category.id == CategoryKeyword.category_id)
        .filter(_scope_filter(user_id, family_group_id))
        .all()
    )
    if not rows:
        return None

    tokens = _tokens(desc)
    best_id = None
    best_score = (-1, -1)  # (level, keyword_length)

    for keyword, cat_id, level in rows:
        kw = keyword or ""
        if " " in kw:
            hit = kw in desc
        else:
            hit = kw in tokens
        if not hit:
            continue
        score = (level or 0, len(kw))
        if score > best_score:
            best_score = score
            best_id = str(cat_id)

    return best_id


# ── 2. Groq LLM fallback ──────────────────────────────────────────────────────

def _build_category_tree(
    db: Session, user_id: str, family_group_id: str | None
) -> list[dict]:
    """User's (or family's) full category tree (root → children → grandchildren)."""
    roots = (
        db.query(Category)
        .filter(_scope_filter(user_id, family_group_id), Category.parent_id.is_(None))
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


def _groq_suggest(description: str, categories: list[dict]) -> str | None:
    """Ask the LLM to pick a node; return the deepest valid node id, else None."""
    prompt = f"""You are a multilingual expense categorizer for an Indian personal finance app.

Expense description (may be Hindi, Punjabi, Hinglish, English, or any mix):
"{description}"

User's category tree (JSON):
{json.dumps(categories, ensure_ascii=False)}

Rules:
- Understand the description in any language (e.g. "doodh"→milk, "bijli"→electricity,
  "kiraya"→rent, "petrol"→fuel, "kapde"→clothes, "doctor"→health).
- ALWAYS pick ids from the tree above — never invent one.
- Prefer the MOST SPECIFIC match: grandchild > child > root.

Respond with ONLY this JSON (no markdown):
{{"category_id":"<root uuid>","subcategory_id":<child or grandchild uuid or null>}}"""

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

        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        # The model sometimes adds prose around/after the JSON; extract the
        # first {...} object so a trailing explanation doesn't break parsing.
        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))
        cat_id = data.get("category_id")
        sub_id = data.get("subcategory_id")

        valid_ids = (
            {c["id"] for c in categories}
            | {s["id"] for c in categories for s in c.get("subcategories", [])}
            | {
                g["id"]
                for c in categories
                for s in c.get("subcategories", [])
                for g in s.get("subcategories", [])
            }
        )
        # Prefer the deepest valid id the model returned
        if sub_id and sub_id in valid_ids:
            return sub_id
        if cat_id and cat_id in valid_ids:
            return cat_id
        return None

    except Exception as exc:
        logger.warning("Groq category suggestion failed: %s", exc)
        return None
