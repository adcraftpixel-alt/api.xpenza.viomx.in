"""
Canonical default category tree (3 levels: root → sub → leaf) plus the
multilingual keyword aliases used by the hybrid categorizer.

This is the SINGLE source of truth for default categories. Onboarding,
`/categories/seed-defaults`, and family-group creation all seed from here,
so personal and family trees stay consistent.

Structure per node:
    {"name", "icon", "keywords": [...], "children": [...]}

Keywords are English + Hindi/Punjabi transliterations for the SAME concept,
e.g. milk / doodh / dudh. They are stored lowercased in `category_keywords`
and matched against the typed item name (Phase 3). A node inherits its
root's colour so a category and its sub-tree read as one group in the UI.
"""
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.category_keyword import CategoryKeyword


DEFAULT_TREE: list[dict] = [
    {
        "name": "Groceries", "icon": "🛒", "color": "#22C55E",
        "keywords": ["grocery", "groceries", "kirana", "ration", "supermarket",
                     "bigbasket", "dmart", "blinkit", "zepto", "instamart", "jiomart"],
        "children": [
            {
                "name": "Dairy Product", "icon": "🥛",
                "keywords": ["dairy", "milk products"],
                "children": [
                    {"name": "Milk",          "keywords": ["milk", "doodh", "dudh"]},
                    {"name": "Curd",          "keywords": ["curd", "dahi", "yogurt", "yoghurt"]},
                    {"name": "Paneer",        "keywords": ["paneer", "cottage cheese"]},
                    {"name": "Butter & Ghee", "keywords": ["butter", "makhan", "ghee", "desi ghee"]},
                    {"name": "Cheese",        "keywords": ["cheese"]},
                ],
            },
            {"name": "Vegetables", "icon": "🥦",
             "keywords": ["vegetable", "vegetables", "sabzi", "sabji", "bhaji", "mandi",
                          "veggies", "tamatar", "tomato", "aloo", "potato", "pyaaz", "onion"]},
            {"name": "Fruits", "icon": "🍎",
             "keywords": ["fruit", "fruits", "phal", "banana", "kela", "apple", "seb",
                          "mango", "aam", "orange"]},
            {"name": "Staples & Grains", "icon": "🌾",
             "keywords": ["rice", "chawal", "atta", "flour", "dal", "pulses", "oil", "tel",
                          "sugar", "cheeni", "salt", "namak", "rava", "sooji", "masala", "spices"]},
            {"name": "Snacks & Packaged", "icon": "🍿",
             "keywords": ["biscuit", "chips", "namkeen", "maggi", "noodles", "chocolate",
                          "packaged", "water bottle", "mineral water", "bottled water",
                          "bisleri", "kinley", "aquafina"]},
        ],
    },
    {
        "name": "Food & Dining", "icon": "🍔", "color": "#EF4444",
        "keywords": ["food", "khana", "khaana", "dining", "meal", "eat out"],
        "children": [
            {"name": "Restaurant", "icon": "🍽️",
             "keywords": ["restaurant", "hotel", "dhaba", "dine", "dinner", "lunch",
                          "thali", "biryani", "pizza", "burger"]},
            {"name": "Tea & Coffee", "icon": "☕",
             "keywords": ["tea", "chai", "coffee", "cafe", "latte", "cappuccino"]},
            {"name": "Online Food", "icon": "🛵",
             "keywords": ["zomato", "swiggy", "online food", "food delivery", "order food"]},
            {"name": "Street Food & Snacks", "icon": "🌮",
             "keywords": ["snack", "chaat", "samosa", "vada pav", "street food",
                          "pani puri", "golgappa", "pakoda"]},
            {"name": "Sweets & Bakery", "icon": "🍰",
             "keywords": ["sweet", "mithai", "cake", "bakery", "pastry", "dessert", "ice cream"]},
        ],
    },
    {
        "name": "Transport", "icon": "🚗", "color": "#3B82F6",
        "keywords": ["transport", "commute", "travel local"],
        "children": [
            {"name": "Fuel", "icon": "⛽",
             "keywords": ["petrol", "diesel", "fuel", "cng", "tanki", "petrol pump"]},
            {"name": "Cab & Auto", "icon": "🚕",
             "keywords": ["uber", "ola", "cab", "taxi", "auto", "rickshaw", "rapido"]},
            {"name": "Public Transport", "icon": "🚌",
             "keywords": ["bus", "metro", "train", "local", "ticket", "irctc", "redbus"]},
            {"name": "Parking & Toll", "icon": "🅿️",
             "keywords": ["parking", "toll", "fastag", "challan"]},
            {"name": "Vehicle Service", "icon": "🔧",
             "keywords": ["service", "repair", "mechanic", "puncture", "car wash", "spare parts"]},
        ],
    },
    {
        "name": "Housing", "icon": "🏠", "color": "#6366F1",
        "keywords": ["house", "home", "ghar"],
        "children": [
            {"name": "Rent", "icon": "🏘️",
             "keywords": ["rent", "kiraya", "kira", "house rent", "room rent", "pg", "flat rent"]},
            {"name": "EMI & Loan", "icon": "🏦",
             "keywords": ["emi", "home loan", "mortgage", "loan"]},
            {"name": "Maintenance", "icon": "🧰",
             "keywords": ["maintenance", "society", "plumber", "electrician", "carpenter"]},
        ],
    },
    {
        "name": "Bills & Utilities", "icon": "⚡", "color": "#F59E0B",
        "keywords": ["bill", "bills", "utility", "utilities"],
        "children": [
            {"name": "Electricity", "icon": "💡",
             "keywords": ["electricity", "electric", "bijli", "light bill", "power bill"]},
            {"name": "Water", "icon": "💧",
             "keywords": ["water", "paani", "water bill"]},
            {"name": "Gas", "icon": "🔥",
             "keywords": ["gas", "cylinder", "lpg", "gas bill"]},
            {"name": "Internet & Mobile", "icon": "📶",
             "keywords": ["wifi", "internet", "broadband", "mobile", "recharge", "sim",
                          "jio", "airtel", "bsnl", "postpaid", "prepaid", "dth", "cable"]},
        ],
    },
    {
        "name": "Shopping", "icon": "👕", "color": "#8B5CF6",
        "keywords": ["shopping", "shop", "buy", "purchase", "amazon", "flipkart",
                     "myntra", "meesho"],
        "children": [
            {"name": "Clothing", "icon": "👗",
             "keywords": ["clothes", "cloth", "kapde", "kapda", "shirt", "pant", "jeans",
                          "kurta", "saree", "dress", "tshirt", "top"]},
            {"name": "Footwear", "icon": "👟",
             "keywords": ["shoes", "footwear", "sandal", "slipper", "chappal", "juta"]},
            {"name": "Electronics", "icon": "📱",
             "keywords": ["electronics", "laptop", "charger", "headphone", "gadget",
                          "tv", "appliance"]},
            {"name": "Home & Furniture", "icon": "🛋️",
             "keywords": ["furniture", "decor", "utensils", "bartan", "curtain"]},
        ],
    },
    {
        "name": "Health & Medical", "icon": "🏥", "color": "#10B981",
        "keywords": ["health", "medical", "illaj"],
        "children": [
            {"name": "Medicine", "icon": "💊",
             "keywords": ["medicine", "dawai", "dawa", "tablet", "capsule", "syrup",
                          "pharmacy", "chemist", "medplus", "apollo",
                          "paracetamol", "crocin", "dolo", "combiflam", "antibiotic",
                          "azithromycin", "amoxicillin", "painkiller", "antacid",
                          "ointment", "drops", "vicks", "vitamin", "bandage", "dettol",
                          "insulin", "cough syrup"]},
            {"name": "Doctor & Hospital", "icon": "🩺",
             "keywords": ["doctor", "hospital", "clinic", "consultation", "checkup", "opd"]},
            {"name": "Tests & Lab", "icon": "🧪",
             "keywords": ["lab", "test", "blood test", "scan", "xray", "mri", "diagnostic",
                          "ecg", "ultrasound", "sonography", "ct scan"]},
            {"name": "Fitness & Gym", "icon": "🏋️",
             "keywords": ["gym", "fitness", "yoga", "workout", "protein", "supplement"]},
        ],
    },
    {
        "name": "Entertainment", "icon": "🎬", "color": "#EC4899",
        "keywords": ["entertainment", "fun"],
        "children": [
            {"name": "Streaming & OTT", "icon": "📺",
             "keywords": ["netflix", "prime", "hotstar", "spotify", "ott", "youtube premium",
                          "subscription"]},
            {"name": "Movies & Events", "icon": "🎟️",
             "keywords": ["movie", "cinema", "pvr", "inox", "bookmyshow", "concert",
                          "event", "show"]},
            {"name": "Gaming", "icon": "🎮",
             "keywords": ["game", "gaming", "steam", "playstation", "xbox"]},
        ],
    },
    {
        "name": "Education", "icon": "🎓", "color": "#0EA5E9",
        "keywords": ["education", "padhai", "study"],
        "children": [
            {"name": "Fees", "icon": "🏫",
             "keywords": ["school", "college", "fees", "fee", "tuition", "coaching", "admission"]},
            {"name": "Books & Stationery", "icon": "📚",
             "keywords": ["book", "books", "kitab", "notebook", "stationery", "pen", "pencil"]},
            {"name": "Courses", "icon": "💻",
             "keywords": ["course", "udemy", "coursera", "online course", "class"]},
        ],
    },
    {
        "name": "Personal Care", "icon": "💇", "color": "#F472B6",
        "keywords": ["personal care", "grooming"],
        "children": [
            {"name": "Salon & Spa", "icon": "💆",
             "keywords": ["salon", "haircut", "barber", "parlour", "parlor", "spa",
                          "massage", "baal"]},
            {"name": "Cosmetics", "icon": "💄",
             "keywords": ["cosmetic", "makeup", "cream", "lotion", "skincare", "perfume",
                          "shampoo"]},
        ],
    },
    {
        "name": "Investments", "icon": "📈", "color": "#14B8A6",
        "keywords": ["invest", "investment"],
        "children": [
            {"name": "SIP & Mutual Funds", "icon": "📊",
             "keywords": ["sip", "mutual fund", "mf"]},
            {"name": "Stocks", "icon": "📉",
             "keywords": ["stock", "stocks", "shares", "equity", "demat"]},
            {"name": "Deposits & Insurance", "icon": "🛡️",
             "keywords": ["fd", "fixed deposit", "rd", "ppf", "nps", "insurance",
                          "premium", "policy", "lic"]},
            {"name": "Gold", "icon": "🥇",
             "keywords": ["gold", "sona", "silver", "chandi"]},
        ],
    },
    {
        "name": "Travel", "icon": "✈️", "color": "#0D9488",
        "keywords": ["travel", "trip", "vacation", "holiday", "tour", "ghoomna"],
        "children": [
            {"name": "Flights", "icon": "✈️",
             "keywords": ["flight", "airline", "indigo", "air ticket"]},
            {"name": "Hotels & Stay", "icon": "🏨",
             "keywords": ["resort", "oyo", "airbnb", "lodge", "hotel booking", "hotel stay"]},
            {"name": "Holiday Package", "icon": "🏖️",
             "keywords": ["tour package", "goibibo", "makemytrip", "holiday package"]},
        ],
    },
    {
        "name": "General", "icon": "💰", "color": "#6B7280",
        "keywords": ["general", "misc", "miscellaneous", "other", "others"],
        "children": [],
    },
]


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _seed_keywords(db: Session, category: Category, keywords: list[str]) -> int:
    if not keywords:
        return 0
    existing = {
        row[0]
        for row in db.query(CategoryKeyword.keyword)
        .filter(CategoryKeyword.category_id == category.id)
        .all()
    }
    added = 0
    for kw in keywords:
        k = _norm(kw)
        if k and k not in existing:
            db.add(CategoryKeyword(category_id=category.id, keyword=k, source="seed"))
            existing.add(k)
            added += 1
    return added


def seed_category_tree(
    db: Session, *, user_id: str, family_group_id: str | None = None
) -> int:
    """
    Idempotently seed the default 3-level tree + keywords into a scope.

    - Personal scope:  user_id set, family_group_id=None
    - Family scope:    family_group_id set (user_id = the creator/owner)

    Existing roots are reused by name (so legacy flat categories get their
    sub-tree attached instead of being duplicated). Returns # categories created.
    """
    created = 0

    def scope_query():
        q = db.query(Category)
        if family_group_id:
            return q.filter(Category.family_group_id == family_group_id)
        return q.filter(
            Category.user_id == user_id, Category.family_group_id.is_(None)
        )

    def find_or_create(name, parent, level, icon, color) -> Category:
        nonlocal created
        q = scope_query().filter(Category.name == name)
        q = q.filter(
            Category.parent_id == parent.id if parent else Category.parent_id.is_(None)
        )
        node = q.first()
        if node:
            return node
        node = Category(
            user_id=user_id,
            family_group_id=family_group_id,
            parent_id=parent.id if parent else None,
            name=name,
            icon=icon,
            color=color,
            level=level,
            is_default=True,
        )
        db.add(node)
        db.flush()
        created += 1
        return node

    for root in DEFAULT_TREE:
        color = root.get("color")
        root_node = find_or_create(root["name"], None, 0, root.get("icon"), color)
        _seed_keywords(db, root_node, root.get("keywords", []))
        for sub in root.get("children", []):
            sub_node = find_or_create(sub["name"], root_node, 1, sub.get("icon"), color)
            _seed_keywords(db, sub_node, sub.get("keywords", []))
            for leaf in sub.get("children", []):
                leaf_node = find_or_create(
                    leaf["name"], sub_node, 2, leaf.get("icon"), color
                )
                _seed_keywords(db, leaf_node, leaf.get("keywords", []))

    db.commit()
    return created
