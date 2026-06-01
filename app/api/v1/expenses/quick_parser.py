import re
from typing import Optional

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    'Groceries': [
        'sugar', 'salt', 'rice', 'dal', 'milk', 'bread', 'butter', 'egg', 'eggs',
        'oil', 'ghee', 'vegetable', 'veggie', 'sabzi', 'fruit', 'atta', 'maida',
        'grocery', 'kiryana', 'onion', 'potato', 'tomato', 'flour', 'dahi', 'paneer',
        'aata', 'masala', 'spice', 'biscuit', 'biscuits', 'namkeen',
    ],
    'Food & Dining': [
        'tea', 'chai', 'coffee', 'snack', 'snacks', 'restaurant', 'hotel', 'pizza',
        'burger', 'biryani', 'meal', 'lunch', 'dinner', 'breakfast', 'juice',
        'samosa', 'idli', 'dosa', 'food', 'eat', 'thali', 'paratha', 'roti',
        'khana', 'dhaba', 'zomato', 'swiggy', 'canteen', 'nasta', 'nashta',
        'vada', 'pav', 'pani', 'lassi',
    ],
    'Transport': [
        'bus', 'auto', 'rickshaw', 'uber', 'ola', 'metro', 'train', 'taxi',
        'petrol', 'diesel', 'fuel', 'cab', 'travel', 'ticket', 'ricksha',
        'rapido', 'bike', 'parking', 'toll', 'fare',
    ],
    'Shopping': [
        'clothes', 'shirt', 'pant', 'shoes', 'dress', 'amazon', 'flipkart',
        'buy', 'purchase', 'jeans', 'kurta', 'saree', 'top', 'jacket', 'bag',
        'watch', 'mobile', 'phone', 'gadget', 'electronics',
    ],
    'Bills & Utilities': [
        'electricity', 'bill', 'wifi', 'internet', 'recharge', 'gas',
        'cylinder', 'water', 'jio', 'airtel', 'bsnl', 'vi',
        'broadband', 'dth', 'cable', 'rent', 'emi',
    ],
    'Health': [
        'medicine', 'tablet', 'tablets', 'doctor', 'hospital', 'pharmacy',
        'medical', 'dawai', 'dawa', 'chemist', 'clinic', 'injection',
        'vitamin', 'syrup', 'health',
    ],
    'Entertainment': [
        'movie', 'netflix', 'spotify', 'game', 'cinema', 'concert', 'hotstar',
        'prime', 'youtube', 'fun', 'outing', 'party',
    ],
    'Personal Care': [
        'haircut', 'salon', 'spa', 'parlour', 'beauty', 'baal', 'shampoo',
        'soap', 'toothpaste', 'toothbrush', 'cream', 'lotion', 'deodorant',
    ],
    'Education': [
        'book', 'books', 'course', 'fee', 'school', 'college', 'tuition',
        'class', 'pen', 'pencil', 'notebook', 'stationery',
    ],
}


def auto_categorize(description: str) -> str:
    """Auto-categorize based on description keywords."""
    desc_lower = description.lower().strip()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            return category
    return 'Others'


def parse_quick_text(text: str) -> list[dict]:
    """
    Parse natural language expense text.
    Handles formats:
    - "250/- sugar"
    - "50 snacks"
    - "₹180 tea"
    - "250/- sugar, 50/- snacks, 180 tea"
    - "250 sugar\\n50 snacks"
    """
    items = []
    # Split by comma or newline
    parts = re.split(r'[,\n]+', text)

    # Pattern: optional ₹/Rs prefix, amount, optional /-, description
    pattern = re.compile(
        r'(?:₹|Rs\.?\s*)?(\d+(?:\.\d{1,2})?)\s*(?:[\/\-]+\s*)?(.*)',
        re.IGNORECASE
    )

    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = pattern.match(part)
        if match:
            amount_str = match.group(1)
            description = match.group(2).strip()

            if not amount_str:
                continue
            try:
                amount = float(amount_str)
            except ValueError:
                continue

            if amount <= 0:
                continue

            if not description:
                description = 'Expense'

            category = auto_categorize(description)
            items.append({
                'amount': amount,
                'description': description.capitalize(),
                'category': category,
                'auto_categorized': True,
            })

    return items
