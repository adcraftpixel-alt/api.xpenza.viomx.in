"""
Standalone test of the DB-keyword categorization layer.

Loads the REAL seed data (app/api/v1/categories/default_tree.py :: DEFAULT_TREE)
and faithfully replicates the production keyword resolver from
app/api/v1/expenses/ai_categorizer.py (_norm, _tokens, level+length scoring,
deepest-node path walk).

This validates the OFFLINE keyword path only. Entries with no keyword hit fall
to the Groq LLM in production (if GROQ_API_KEY is set), else to "General" — those
are reported as "NO KEYWORD (LLM/General)".

Run:  python3 scripts/test_categorization.py
"""
import ast
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TREE_FILE = os.path.join(HERE, "..", "app", "api", "v1", "categories", "default_tree.py")


# ── load DEFAULT_TREE from the real source file (no backend imports needed) ──────
def load_default_tree() -> list:
    with open(TREE_FILE, "r", encoding="utf-8") as f:
        module = ast.parse(f.read())
    for node in module.body:
        # plain assignment: DEFAULT_TREE = [...]
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DEFAULT_TREE":
                    return ast.literal_eval(node.value)
        # annotated assignment: DEFAULT_TREE: list[dict] = [...]
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "DEFAULT_TREE":
                return ast.literal_eval(node.value)
    raise RuntimeError("DEFAULT_TREE not found")


# ── production helpers, replicated verbatim ──────────────────────────────────────
def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _tokens(s: str) -> set:
    s = (s or "").lower()
    toks = set(re.findall(r"\w+", s))
    for w in re.findall(r"\w[\w\-/]*\w", s):
        if "-" in w or "/" in w:
            toks.add(re.sub(r"[-/]", "", w))
    return toks


# Flatten the tree into (keyword, level, path) rows, mirroring category_keywords.
def build_keyword_rows(tree: list) -> list:
    rows = []  # (keyword_normalized, level, path_list)

    def walk(node, level, path):
        path = path + [node["name"]]
        for kw in node.get("keywords", []):
            rows.append((_norm(kw), level, path))
        for child in node.get("children", []):
            walk(child, level + 1, path)

    for root in tree:
        walk(root, 0, [])
    return rows


# Replicates _keyword_match: single-word keyword matches on token boundary,
# multi-word matches as a phrase substring; best = (level, len(keyword)).
def resolve(desc: str, rows: list):
    desc_n = _norm(desc)
    tokens = _tokens(desc_n)
    best_path = None
    best_score = (-1, -1)
    for kw, level, path in rows:
        if " " in kw:
            hit = kw in desc_n
        else:
            hit = kw in tokens
        if not hit:
            continue
        score = (level, len(kw))
        if score > best_score:
            best_score = score
            best_path = path
    return best_path


# ── test entries (English, Hindi/Hinglish, multi-word, formats) ──────────────────
ENTRIES = [
    # Groceries
    "Milk", "Doodh", "Curd", "Dahi", "Paneer", "Butter", "Ghee", "Cheese",
    "Tomato", "Aloo", "Pyaaz", "Sabzi", "Banana", "Kela", "Apple",
    "Rice", "Chawal", "Atta", "Dal", "Sugar", "Cheeni", "Maggi", "Biscuit",
    "Bigbasket order", "Zepto",
    # Food & Dining
    "Tea", "Chai", "Coffee", "Restaurant", "Pizza", "Biryani",
    "Zomato", "Swiggy order", "Samosa", "Pani puri", "Cake", "Ice cream",
    # Transport
    "Petrol", "Diesel", "Petrol pump", "Uber", "Ola", "Auto", "Rapido",
    "Bus", "Metro", "Train ticket", "Parking", "Toll", "Fastag", "Car service",
    # Housing
    "Rent", "Kiraya", "House rent", "EMI", "Home loan", "Plumber",
    # Bills & Utilities
    "Electricity", "Bijli", "Light bill", "Water", "Paani", "Gas cylinder",
    "Wifi", "Internet", "Recharge", "Jio recharge", "Airtel postpaid", "DTH",
    # Shopping
    "Clothes", "Kapde", "Shirt", "Saree", "Shoes", "Chappal",
    "Laptop", "Charger", "Headphone", "Furniture", "Amazon order",
    # Health & Medical
    "Medicine", "Dawai", "Tablet", "Doctor", "Hospital", "Blood test",
    "X-ray", "Gym", "Yoga", "Protein",
    # Entertainment
    "Netflix", "Spotify", "Hotstar", "Movie", "PVR", "BookMyShow", "Steam game",
    # Education
    "School fees", "Tuition", "Book", "Notebook", "Udemy course",
    # Personal Care
    "Salon", "Haircut", "Barber", "Shampoo", "Makeup", "Perfume",
    # Investments
    "SIP", "Mutual fund", "Stocks", "FD", "PPF", "Insurance premium", "Gold", "Sona",
    # Travel
    "Flight", "Indigo air ticket", "OYO", "Resort", "MakeMyTrip package",
    # No-keyword (should fall to LLM / General)
    "Paracetamol", "Crocin", "iPhone", "Cigarette", "Gift", "Donation",
    "Haldiram", "Burger King", "Salary", "Random xyz",
]


def main():
    tree = load_default_tree()
    rows = build_keyword_rows(tree)

    roots = len(tree)
    subs = sum(len(c.get("children", [])) for r in tree for c in [r] for c in r.get("children", []))
    # count properly
    n_root = len(tree)
    n_sub = 0
    n_leaf = 0
    for r in tree:
        for c in r.get("children", []):
            n_sub += 1
            n_leaf += len(c.get("children", []))
    total = n_root + n_sub + n_leaf

    print("=" * 72)
    print(f"CATEGORY TREE: {n_root} top-level, {n_sub} subcategories, "
          f"{n_leaf} leaf nodes  →  {total} nodes total")
    print(f"Keyword aliases seeded: {len(rows)}")
    print("=" * 72)
    print(f"{'ENTRY':<22} {'RESOLVES TO'}")
    print("-" * 72)

    matched = 0
    nokey = 0
    for e in ENTRIES:
        path = resolve(e, rows)
        if path:
            matched += 1
            print(f"{e:<22} {' › '.join(path)}")
        else:
            nokey += 1
            print(f"{e:<22} (no keyword → LLM if GROQ_API_KEY, else General)")

    print("-" * 72)
    print(f"{matched}/{len(ENTRIES)} matched by keyword | "
          f"{nokey} need LLM/General fallback")


if __name__ == "__main__":
    main()
