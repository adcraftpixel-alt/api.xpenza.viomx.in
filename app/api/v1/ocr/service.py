import os
import re
import base64
import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session

import httpx

from app.models.ocr_scan import OCRScan
from app.utils.storage import upload_to_s3, generate_unique_filename

logger = logging.getLogger(__name__)

_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_VISION_PROMPT = (
    "This is a receipt or bill image. Extract every individual product/service line item with its price. "
    "Return ONLY a raw JSON array — no markdown, no explanation, no code fences. "
    "Format: [{\"description\": \"Item Name\", \"amount\": 13.00, \"category\": \"Groceries\", \"merchant\": \"Store Name\"}] "
    "Rules:\n"
    "- description: product name in Title Case, 1-4 words, clean and concise\n"
    "- amount: the line item price as a float (the rightmost price on that line)\n"
    "- category: exactly one of: Groceries, Food & Dining, Transport, Shopping, "
    "Bills & Utilities, Health, Entertainment, Personal Care, Education, Others\n"
    "- merchant: put the store/merchant name in EVERY item (same value for all items from the same bill)\n"
    "- Skip: subtotals, grand totals, taxes, GST, discounts, dates, addresses, phone numbers\n"
    "- If you cannot read an item clearly, skip it\n"
    "Grocery keywords → Groceries: flour, rice, dal, oil, soap, noodles, bread, milk, sugar, spices"
)

# ── Groq Vision ───────────────────────────────────────────────────────────────

def _extract_with_groq_vision(file_bytes: bytes) -> list:
    """Send image to Groq Vision, get structured line items back."""
    # Detect MIME type from magic bytes
    if file_bytes[:3] == b'\xff\xd8\xff':
        mime = "image/jpeg"
    elif file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"
    elif file_bytes[:4] == b'RIFF':
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    image_b64 = base64.b64encode(file_bytes).decode("utf-8")

    with httpx.Client(timeout=25.0) as client:
        resp = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _GROQ_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{image_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": _VISION_PROMPT,
                            },
                        ],
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 1200,
            },
        )
        resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if model wrapped in them
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    start = content.find("[")
    end = content.rfind("]") + 1
    if start < 0 or end <= start:
        logger.warning(f"Groq vision: no JSON array in response: {content[:200]}")
        return []

    raw = json.loads(content[start:end])
    items = []
    merchant = None

    for item in raw:
        if not isinstance(item, dict):
            continue
        amt = float(item.get("amount") or 0)
        desc = str(item.get("description") or "").strip()
        cat = str(item.get("category") or "Others").strip()
        m = str(item.get("merchant") or "").strip()
        if m and not merchant:
            merchant = m
        if amt > 0 and desc:
            items.append({
                "description": desc,
                "amount": round(amt, 2),
                "category": cat,
            })

    return items, merchant or "Unknown Merchant"


# ── Text-based helpers (used when Google Vision OCR provides raw text) ────────

AMOUNT_PATTERNS = [
    r'(?:total|amount|grand total|bill amount|net amount|payable)[:\s]+(?:rs\.?|₹|inr)?\s*([\d,]+\.?\d*)',
    r'(?:rs\.?|₹|inr)\s*([\d,]+\.?\d*)',
    r'([\d,]+\.\d{2})\s*(?:only|/-)',
]

DATE_PATTERNS = [
    r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
    r'(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})',
    r'(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{2,4})',
]


def extract_amount(text: str) -> tuple:
    text_lower = text.lower()
    for pattern in AMOUNT_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "")), 0.9
            except (ValueError, IndexError):
                pass
    numbers = re.findall(r'[\d,]+\.\d{2}', text)
    if numbers:
        amounts = [float(n.replace(",", "")) for n in numbers]
        return max(amounts), 0.5
    return 0.0, 0.0


def extract_merchant(text: str) -> tuple:
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 2]
    if lines:
        merchant = lines[0][:50]
        for noise in ["receipt", "invoice", "bill", "tax invoice"]:
            merchant = re.sub(noise, "", merchant, flags=re.IGNORECASE).strip()
        if merchant:
            return merchant, 0.75
    return "Unknown Merchant", 0.3


def extract_date(text: str) -> tuple:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1), 0.85
    return datetime.utcnow().strftime("%Y-%m-%d"), 0.2


def categorize_from_merchant(merchant: str, text: str) -> str:
    combined = (merchant + " " + text).lower()
    rules = {
        "Groceries": ["grocery", "supermarket", "maida", "atta", "flour", "rice", "dal", "oil",
                      "ghee", "sugar", "salt", "soap", "noodles", "bread", "milk", "besan",
                      "shampoo", "detergent", "maggi", "biscuit", "namkeen"],
        "Food & Dining": ["restaurant", "food", "cafe", "pizza", "biryani", "hotel",
                          "dhaba", "swiggy", "zomato", "ice cream", "snack"],
        "Transport": ["fuel", "petrol", "diesel", "cab", "taxi", "uber", "ola",
                      "train", "bus", "flight", "parking"],
        "Shopping": ["mart", "store", "shop", "mall", "retail", "amazon", "flipkart"],
        "Bills & Utilities": ["electricity", "water", "gas", "internet",
                              "mobile", "recharge", "bill"],
        "Health": ["pharmacy", "medical", "hospital", "clinic", "medicine", "drug"],
        "Entertainment": ["cinema", "movie", "theatre", "netflix", "spotify"],
    }
    for category, keywords in rules.items():
        if any(kw in combined for kw in keywords):
            return category
    return "Shopping"


def extract_line_items(text: str) -> list:
    skip_keywords = [
        "total", "amount", "bill", "payable", "net", "subtotal", "sub total",
        "tax", "gst", "cgst", "sgst", "discount", "receipt", "invoice",
        "date", "time", "cash", "change", "paid", "balance", "thank", "mrp",
        "rate", "qty", "item", "description", "hsn", "pan", "gstin", "tel",
        "mob", "phone", "address", "email", "website", "www", "image", "size",
    ]
    items = []
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]

    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in skip_keywords):
            continue
        numbers = re.findall(r"[\d,]+\.?\d{0,2}", line)
        if not numbers:
            continue
        try:
            amount = float(numbers[-1].replace(",", ""))
        except ValueError:
            continue
        if amount <= 0 or amount > 50000:
            continue
        first_num_match = re.search(r"\s+\d", line)
        name = line[: first_num_match.start()].strip() if first_num_match else line
        name = re.sub(r"[^a-zA-Z0-9\s&\-/.]", "", name).strip()
        if len(name) < 2:
            continue
        name = " ".join(w.capitalize() for w in name.split())
        items.append({
            "description": name,
            "amount": round(amount, 2),
            "category": categorize_from_merchant(name, name),
        })
    return items


# ── OCR Service ───────────────────────────────────────────────────────────────

class OCRService:

    def process_image(self, file_bytes: bytes, filename: str, user_id: str, db: Session) -> dict:
        """Process receipt image — returns extracted expense data."""
        unique_name = f"receipts/{user_id}/{generate_unique_filename(filename)}"
        image_url = ""
        try:
            image_url = upload_to_s3(file_bytes, unique_name, "image/jpeg")
        except Exception as e:
            logger.warning(f"S3 upload skipped (no credentials): {e}")

        # ── 1. Google Vision (best accuracy, requires credentials) ──────────
        raw_text = ""
        try:
            from app.config import settings
            if hasattr(settings, "GOOGLE_CLOUD_CREDENTIALS") and \
                    settings.GOOGLE_CLOUD_CREDENTIALS not in ("", "{}"):
                from google.cloud import vision
                client = vision.ImageAnnotatorClient()
                image = vision.Image(content=file_bytes)
                response = client.document_text_detection(image=image)
                raw_text = response.full_text_annotation.text
                logger.info("Google Vision OCR succeeded")
        except Exception as e:
            logger.info(f"Google Vision not available: {e}")

        # ── 2. Groq Vision (primary fallback — no extra credentials needed) ─
        groq_items = []
        merchant_name = "Unknown Merchant"
        if not raw_text:
            try:
                result = _extract_with_groq_vision(file_bytes)
                groq_items, merchant_name = result
                logger.info(f"Groq Vision extracted {len(groq_items)} items")
            except Exception as e:
                logger.warning(f"Groq Vision failed: {e}")

        # ── 3. If Groq Vision returned items, use them directly ─────────────
        if groq_items:
            total = sum(i["amount"] for i in groq_items)
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

            scan = OCRScan(
                user_id=user_id,
                image_url=image_url,
                raw_text=f"Groq Vision: {len(groq_items)} items extracted",
                extracted_data={
                    "amount": total,
                    "date": date_str,
                    "merchant": merchant_name,
                    "confidence": 0.90,
                    "line_items": groq_items,
                },
                status="completed",
            )
            db.add(scan)
            db.commit()
            db.refresh(scan)

            return {
                "scan_id": str(scan.id),
                "amount": total,
                "merchant": merchant_name,
                "date": date_str,
                "category": groq_items[0]["category"] if groq_items else "Others",
                "confidence": 0.90,
                "raw_text": None,
                "line_items": groq_items,
                "status": "completed",
                "source": "groq_vision",
            }

        # ── 4. Text-based extraction (Google Vision raw_text path) ──────────
        if not raw_text:
            raw_text = f"Receipt\nDate: {datetime.utcnow().strftime('%d/%m/%Y')}\nAmount: ₹0.00"

        amount, amount_conf = extract_amount(raw_text)
        merchant, merchant_conf = extract_merchant(raw_text)
        date_str, date_conf = extract_date(raw_text)
        category = categorize_from_merchant(merchant, raw_text)
        line_items = extract_line_items(raw_text)
        overall_confidence = (amount_conf + merchant_conf + date_conf) / 3

        scan = OCRScan(
            user_id=user_id,
            image_url=image_url,
            raw_text=raw_text,
            extracted_data={
                "amount": amount,
                "date": date_str,
                "merchant": merchant,
                "category": category,
                "confidence": round(overall_confidence, 2),
                "line_items": line_items,
            },
            status="completed",
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)

        return {
            "scan_id": str(scan.id),
            "amount": amount,
            "merchant": merchant,
            "date": date_str,
            "category": category,
            "confidence": round(overall_confidence, 2),
            "raw_text": raw_text[:500] if raw_text else None,
            "line_items": line_items,
            "status": "completed",
            "source": "text_extraction",
        }


ocr_service = OCRService()
