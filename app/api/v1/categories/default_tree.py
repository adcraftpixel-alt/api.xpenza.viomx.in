"""
Canonical default category tree (2 levels: root → sub) plus the
multilingual keyword aliases used by the hybrid categorizer.

This is the SINGLE source of truth for default categories. Onboarding,
`/categories/seed-defaults`, and family-group creation all seed from here,
so personal and family trees stay consistent.

Mirrors the live tree tenant +919878101955 has (root/sub names, icons,
colors, keywords) — the original enrichment ran one-off against the DB via
scripts/seed_existing_root_subcategories.py and never made it back into
onboarding until now. No third level: subcategories carry keywords directly.

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
        "keywords": [],
        "children": [
            {"name": "Dairy Product", "icon": "🥛",
             "keywords": ["dairy", "milk products", "milk", "doodh", "dudh", "curd", "dahi",
                          "yogurt", "yoghurt", "paneer", "cottage cheese", "butter", "makhan",
                          "ghee", "desi ghee", "cheese"]},
            {"name": "Vegetables", "icon": "🥦",
             "keywords": ["vegetable", "vegetables", "sabzi", "sabji", "bhaji", "mandi", "veggies",
                          "tamatar", "tomato", "aloo", "potato", "pyaaz", "pyaz", "onion", "bhindi",
                          "gobi", "palak", "gajar", "matar", "capsicum", "lauki", "baingan"]},
            {"name": "Fruits", "icon": "🍎",
             "keywords": ["fruit", "fruits", "phal", "banana", "kela", "apple", "seb", "mango", "aam",
                          "orange", "papaya", "guava", "watermelon", "tarbooj", "grapes", "angoor",
                          "anaar", "pomegranate"]},
            {"name": "Staples & Grains", "icon": "🌾",
             "keywords": ["rice", "chawal", "atta", "flour", "dal", "pulses", "oil", "tel",
                          "sugar", "cheeni", "salt", "namak", "rava", "sooji", "masala",
                          "spices", "besan", "poha", "maida", "jeera", "haldi", "mirch",
                          "chai patti"]},
            {"name": "Snacks & Packaged", "icon": "🍿",
             "keywords": ["biscuit", "chips", "namkeen", "maggi", "noodles", "chocolate",
                          "packaged", "water bottle", "mineral water", "bottled water",
                          "bisleri", "kinley", "aquafina"]},
            {"name": "Beverages", "icon": "🥤",
             "keywords": ["cold drink", "soft drink", "juice", "fruit juice", "frooti", "thums up",
                          "pepsi", "coca cola", "coke", "sprite", "limca"]},
        ],
    },
    {
        "name": "Food & Dining", "icon": "🍕", "color": "#EF4444",
        "keywords": [],
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
            {"name": "Alcohol & Tobacco", "icon": "🍺",
             "keywords": ["beer", "wine", "whisky", "whiskey", "rum", "vodka", "cigarette",
                          "gutkha", "paan", "tobacco"]},
        ],
    },
    {
        "name": "Transport / Fuel", "icon": "🚗", "color": "#6366F1",
        "keywords": [],
        "children": [
            {"name": "Fuel", "icon": "⛽",
             "keywords": ["petrol", "diesel", "fuel", "cng", "tanki", "petrol pump"]},
            {"name": "Cab & Auto", "icon": "🚕",
             "keywords": ["uber", "ola", "cab", "taxi", "auto", "rickshaw", "rapido"]},
            {"name": "Public Transport", "icon": "🚌",
             "keywords": ["bus", "metro", "train", "local", "ticket", "irctc", "redbus",
                          "dtc", "best bus", "ac local", "monthly pass", "season ticket"]},
            {"name": "Parking & Toll", "icon": "🅿️",
             "keywords": ["parking", "toll", "fastag", "challan"]},
            {"name": "Vehicle Service", "icon": "🔧",
             "keywords": ["service", "repair", "mechanic", "puncture", "car wash", "spare parts"]},
        ],
    },
    {
        "name": "House Rent / EMI", "icon": "🏠", "color": "#3B82F6",
        "keywords": [],
        "children": [
            {"name": "Rent", "icon": "🏘️",
             "keywords": ["rent", "kiraya", "kira", "house rent", "room rent", "pg", "flat rent"]},
            {"name": "EMI & Loan", "icon": "🏦",
             "keywords": ["emi", "home loan", "mortgage", "loan", "personal loan",
                          "credit card bill", "cc bill", "credit card payment", "gold loan"]},
            {"name": "Maintenance", "icon": "🧰",
             "keywords": ["maintenance", "society", "plumber", "electrician", "carpenter"]},
            {"name": "Household Help", "icon": "🧹",
             "keywords": ["maid", "bai", "kaamwali", "jamadarni", "cook", "cook salary",
                          "maid salary", "driver", "driver salary", "nanny", "babysitter",
                          "ayah"]},
            {"name": "Property Tax", "icon": "🧾",
             "keywords": ["property tax", "house tax", "municipal tax"]},
        ],
    },
    {
        "name": "Bills & Subscriptions", "icon": "📱", "color": "#F59E0B",
        "keywords": [],
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
            {"name": "Newspaper & Courier", "icon": "📰",
             "keywords": ["newspaper", "akhbar", "magazine", "courier", "speed post", "dtdc"]},
            {"name": "Bank & Financial Charges", "icon": "🏦",
             "keywords": ["atm charge", "bank charge", "cheque bounce", "late fee",
                          "penalty", "processing fee"]},
            {"name": "Govt Documents & Legal", "icon": "📄",
             "keywords": ["passport", "aadhar", "aadhaar", "pan card", "stamp paper",
                          "notary", "court fee", "affidavit"]},
            {"name": "Subscriptions & Memberships", "icon": "🔔",
             "keywords": ["amazon prime membership", "gym membership", "club membership",
                          "software subscription", "app subscription"]},
        ],
    },
    {
        "name": "Shopping", "icon": "👕", "color": "#EC4899",
        "keywords": [],
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
            {"name": "Kids & Baby", "icon": "🧸",
             "keywords": ["diaper", "baby food", "formula", "cerelac", "toys", "khilona",
                          "kids wear", "kids clothing"]},
            {"name": "Jewellery", "icon": "💍",
             "keywords": ["jewellery", "jewelry", "gold jewellery", "silver jewellery",
                          "ornaments", "mangalsutra", "ring", "earrings"]},
        ],
    },
    {
        "name": "Health & Medical", "icon": "🏥", "color": "#10B981",
        "keywords": [],
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
            {"name": "Pet Care", "icon": "🐾",
             "keywords": ["dog food", "cat food", "pedigree", "pet food", "vet", "vet clinic",
                          "pet grooming"]},
            {"name": "Dental & Eye Care", "icon": "🦷",
             "keywords": ["dentist", "dental", "optician", "spectacles", "chashma", "lens",
                          "contact lens"]},
        ],
    },
    {
        "name": "Entertainment", "icon": "🎬", "color": "#8B5CF6",
        "keywords": [],
        "children": [
            {"name": "Streaming & OTT", "icon": "📺",
             "keywords": ["netflix", "prime", "hotstar", "spotify", "ott", "youtube premium",
                          "subscription"]},
            {"name": "Movies & Events", "icon": "🎟️",
             "keywords": ["movie", "cinema", "pvr", "inox", "bookmyshow", "concert",
                          "event", "show"]},
            {"name": "Gaming", "icon": "🎮",
             "keywords": ["game", "gaming", "steam", "playstation", "xbox"]},
            {"name": "Festivals, Gifts & Donations", "icon": "🎁",
             "keywords": ["diwali", "holi", "eid", "rakhi", "gift", "tohfa", "chanda", "dan",
                          "temple donation", "puja samagri", "donation", "charity"]},
            {"name": "Hobbies & Sports", "icon": "🏸",
             "keywords": ["cricket kit", "badminton", "sports equipment", "hobby class",
                          "football", "cricket bat"]},
        ],
    },
    {
        "name": "Education", "icon": "🎓", "color": "#0EA5E9",
        "keywords": [],
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
        "name": "Investments", "icon": "📈", "color": "#F97316",
        "keywords": [],
        "children": [
            {"name": "SIP & Mutual Funds", "icon": "📊",
             "keywords": ["sip", "mutual fund", "mf"]},
            {"name": "Stocks", "icon": "📉",
             "keywords": ["stock", "stocks", "shares", "equity", "demat"]},
            {"name": "Deposits & Insurance", "icon": "🛡️",
             "keywords": ["fd", "fixed deposit", "rd", "ppf", "nps", "insurance",
                          "premium", "policy", "lic", "vehicle insurance", "bike insurance",
                          "car insurance", "health insurance", "term insurance"]},
            {"name": "Gold", "icon": "🥇",
             "keywords": ["gold", "sona", "silver", "chandi"]},
            {"name": "Crypto", "icon": "₿",
             "keywords": ["bitcoin", "crypto", "cryptocurrency", "wazirx", "coindcx", "ethereum"]},
        ],
    },
    {
        "name": "Personal Care", "icon": "💆", "color": "#D946EF",
        "keywords": [],
        "children": [
            {"name": "Salon & Spa", "icon": "💆",
             "keywords": ["salon", "haircut", "barber", "parlour", "parlor", "spa",
                          "massage", "baal"]},
            {"name": "Cosmetics", "icon": "💄",
             "keywords": ["cosmetic", "makeup", "cream", "lotion", "skincare", "perfume",
                          "shampoo"]},
            {"name": "Laundry & Dry Clean", "icon": "👔",
             "keywords": ["laundry", "dhobi", "dry clean", "ironing", "istri"]},
        ],
    },
    {
        "name": "Travel", "icon": "✈️", "color": "#14B8A6",
        "keywords": [],
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
        # Root-level safety net: ai_categorizer.suggest_category() falls back
        # to a category literally named "General" when keyword match AND the
        # LLM both fail — without this node that fallback query returns
        # nothing and the expense is saved with category_id=None.
        "name": "General", "icon": "🧾", "color": "#6B7280",
        "keywords": ["other", "others", "miscellaneous", "misc", "general"],
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
