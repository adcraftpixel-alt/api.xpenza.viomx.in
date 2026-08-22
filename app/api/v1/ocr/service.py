import os
import re
import io
import time
import base64
import json
import logging
import itertools
import threading
from datetime import datetime
from sqlalchemy.orm import Session

import httpx
from fastapi import HTTPException
from PIL import Image

from app.config import settings
from app.models.ocr_scan import OCRScan
from app.utils.storage import upload_to_s3, generate_unique_filename

logger = logging.getLogger(__name__)

_GROQ_API_KEY = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
# Pool of Groq keys for OCR vision specifically — each is a separate account
# with its own independent 8000 TPM / 200000 TPD quota. A single key's daily
# quota (200k tokens) turned out to be a real production ceiling (~20-25 full
# multi-item bill scans/day, account-wide) — confirmed by exhausting it
# during testing. Rotating across keys multiplies that ceiling by the pool
# size instead of just sleeping through one account's limit.
_GROQ_API_KEYS = [
    k.strip() for k in
    (settings.GROQ_API_KEYS or os.getenv("GROQ_API_KEYS", "")).split(",")
    if k.strip()
] or [_GROQ_API_KEY]
_key_cycle_lock = threading.Lock()
_key_cycle = itertools.cycle(range(len(_GROQ_API_KEYS)))


def _next_key_start_index() -> int:
    """Round-robins the starting key across calls so consecutive chunk
    requests spread naturally across the pool instead of hammering key #1
    until it's exhausted before ever touching the others."""
    with _key_cycle_lock:
        return next(_key_cycle)


# meta-llama/llama-4-scout(-maverick) and the llama-3.2 vision-preview models
# have all been decommissioned/withdrawn from this account (confirmed via
# direct API probe — 404 model_not_found / 400 model_decommissioned).
# qwen/qwen3.6-27b is a multimodal model still available on this key; it's a
# "thinking" model by default so reasoning_effort="none" is required below to
# get a direct JSON answer instead of a wrapped <think>...</think> block.
_GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

_VISION_PROMPT = (
    "This is a receipt or bill image (or a cropped section of one). Extract every individual "
    "product/service line item with its price. "
    "Read the visible lines in order, top to bottom, exactly ONCE each. Never restart from the top "
    "or repeat a line you already listed — if you reach the bottom of what's visible in THIS image, "
    "stop there. Do not continue with items you are guessing might be below the crop. "
    "Return ONLY a raw JSON array — no markdown, no explanation, no code fences. "
    "Format: [{\"description\": \"Item Name\", \"amount\": 13.00, \"category\": \"Groceries\", \"merchant\": \"Store Name\"}] "
    "Rules:\n"
    "- description: product name in Title Case, 1-4 words, clean and concise\n"
    "- amount: the line item price as a float (the rightmost price on that line)\n"
    "- category: exactly one of: Groceries, Food & Dining, Transport, Shopping, "
    "Bills & Utilities, Health, Entertainment, Personal Care, Education, Others\n"
    "- merchant: put the store/merchant name in EVERY item (same value for all items from the same bill)\n"
    "- Skip: subtotals, grand totals, taxes, GST, discounts, dates, addresses, phone numbers\n"
    "- If you cannot read an item clearly, skip it — do not guess or invent one\n"
    "- Never output the same description+price pair twice\n"
    "Grocery keywords → Groceries: flour, rice, dal, oil, soap, noodles, bread, milk, sugar, spices"
)

# ── Groq Vision ───────────────────────────────────────────────────────────────

def _prepare_image_for_vision(
    file_bytes: bytes, max_dimension: int = 2000, quality: int = 92,
    min_width: int = 1400,
) -> tuple:
    """Downscale + re-encode as JPEG so a phone photo doesn't trip Groq's
    request-size limit (413 Payload Too Large) — a long receipt shot can be
    1-2MB+ as PNG even at modest pixel dimensions, since PNG compresses
    photographic content poorly. Returns (bytes, mime); falls back to the
    original bytes/mime if Pillow can't decode the image.

    Also UPSCALES a narrow crop up to `min_width` — a phone photo of a
    receipt is often only 700-900px wide (long/narrow, multi-column, tiny
    text), well under what the model's vision encoder can resolve. Lanczos
    upscaling doesn't invent detail that isn't there, but it does give a
    patch-based vision encoder more pixels to work with per character,
    which empirically reads as measurably fewer misreads on dense text.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        w, h = img.size
        if w < min_width:
            scale = min_width / w
            img = img.resize(
                (min_width, max(1, round(h * scale))), Image.LANCZOS,
            )
            w, h = img.size
        if max(w, h) > max_dimension:
            scale = max_dimension / max(w, h)
            img = img.resize(
                (max(1, round(w * scale)), max(1, round(h * scale))),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning(f"Image downscale failed, sending original bytes: {e}")
        if file_bytes[:3] == b'\xff\xd8\xff':
            return file_bytes, "image/jpeg"
        if file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return file_bytes, "image/png"
        if file_bytes[:4] == b'RIFF':
            return file_bytes, "image/webp"
        return file_bytes, "image/jpeg"


def _parse_groq_wait(header_val: str) -> float:
    """Parse Groq's rate-limit duration strings ('57.6s', '2m52.8s', '1h2m3s')
    into seconds. Returns 0 for anything unparseable."""
    if not header_val:
        return 0.0
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?$", header_val.strip())
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return (int(h or 0) * 3600) + (int(mi or 0) * 60) + float(s or 0)


def _call_groq_vision_once(image_bytes: bytes, max_retries: int = 2) -> tuple:
    """One Groq Vision call on a single (already receipt-cropped) image.
    Returns (items, merchant, finish_reason, total_tokens, remaining_tokens,
    reset_seconds) — finish_reason 'length' means the model ran out of its
    token budget mid-array (a signal the caller could use to split further);
    remaining_tokens/reset_seconds come straight from Groq's rate-limit
    headers, the account's own authoritative view of its 8000/minute budget
    (far more reliable than any locally-tracked counter, since the limit is
    shared across every request hitting this org, not just this process).

    On a 429, tries every other key in the pool FIRST (each is a separate
    account with its own quota — no reason to wait if a sibling key still
    has budget) before falling back to a sleep-and-retry pass across the
    whole pool. Rate-limiting turned out to have two independent ceilings —
    an 8000/minute window AND a 200,000/day account-wide cap that testing
    actually exhausted — so a single key's limit being hit doesn't mean
    Groq itself is unavailable, just that account.
    """
    prepared_bytes, mime = _prepare_image_for_vision(image_bytes)
    image_b64 = base64.b64encode(prepared_bytes).decode("utf-8")
    payload = {
        "model": _GROQ_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                    },
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
        # 4000 comfortably covers 100+ line items (~30 tokens/item of JSON)
        # while leaving headroom under the account's 8000 TPM cap alongside
        # this call's own prompt tokens (~700-1500 for a typical photo).
        "max_tokens": 4000,
        "reasoning_effort": "none",
    }

    n_keys = len(_GROQ_API_KEYS)
    start = _next_key_start_index()

    resp = None
    for attempt in range(max_retries + 1):
        all_rate_limited = True
        last_wait = 15.0
        for offset in range(n_keys):
            key_idx = (start + offset) % n_keys
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_GROQ_API_KEYS[key_idx]}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code != 429:
                all_rate_limited = False
                break
            last_wait = float(resp.headers.get("retry-after") or 0) or \
                _parse_groq_wait(resp.headers.get("x-ratelimit-reset-tokens", "")) or 15.0
            if n_keys > 1:
                logger.info(f"Groq key #{key_idx + 1}/{n_keys} rate-limited — trying next key")
        if not all_rate_limited:
            break
        if attempt < max_retries:
            logger.info(
                f"All {n_keys} Groq key(s) rate-limited — waiting {last_wait:.0f}s "
                f"(retry {attempt + 1}/{max_retries})"
            )
            time.sleep(last_wait + 1)
    resp.raise_for_status()

    remaining_tokens = int(resp.headers.get("x-ratelimit-remaining-tokens") or 0)
    reset_seconds = _parse_groq_wait(resp.headers.get("x-ratelimit-reset-tokens", ""))

    body = resp.json()
    choice = body["choices"][0]
    finish_reason = choice.get("finish_reason")
    total_tokens = int((body.get("usage") or {}).get("total_tokens") or 0)
    content = choice["message"]["content"].strip()

    # Strip markdown fences if model wrapped in them
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    start = content.find("[")
    if start < 0:
        logger.warning(f"Groq vision: no JSON array in response: {content[:200]}")
        return [], None, finish_reason, total_tokens, remaining_tokens, reset_seconds

    # Parse each `{...}` object individually rather than the whole array in
    # one json.loads — a long bill can still hit max_tokens and get cut off
    # mid-array with no closing `]`. Per-object parsing salvages every
    # complete item before the cutoff instead of losing the whole scan.
    raw = []
    for match in re.finditer(r"\{[^{}]*\}", content[start:]):
        try:
            raw.append(json.loads(match.group(0)))
        except json.JSONDecodeError:
            continue

    # Guard against decoding degeneracy: on long/hard-to-read bills the model
    # can get stuck in a loop instead of stopping — sometimes repeating the
    # exact same line, sometimes drifting through near-identical variants
    # (e.g. "Amul Butter 500g", "Amul Butter 0.005g", "Amul Butter 0.0001g", ...
    # with the amount decaying toward zero each step). Both are the same
    # failure: the description's first two words repeat run after run. Real
    # receipts essentially never have 4+ consecutive lines sharing that
    # prefix, so once that happens everything from the first repeat onward
    # is hallucinated — truncate there.
    def _prefix(item):
        if not isinstance(item, dict):
            return None
        words = str(item.get("description") or "").strip().lower().split()
        return " ".join(words[:2]) or None

    prev_prefix = None
    run_len = 0
    cutoff = len(raw)
    for idx, item in enumerate(raw):
        prefix = _prefix(item)
        if prefix is not None and prefix == prev_prefix:
            run_len += 1
            if run_len >= 4:
                cutoff = idx - run_len + 1
                break
        else:
            prev_prefix = prefix
            run_len = 1
    raw = raw[:cutoff]

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
        # A floor of ₹1 — real line items are essentially never billed
        # below that, and near-zero amounts are a signature of the decaying-
        # hallucination loop the prefix-run guard above doesn't always catch
        # early enough (e.g. it needs 4 repeats to trigger).
        if amt >= 1 and desc:
            items.append({
                "description": desc,
                "amount": round(amt, 2),
                "category": cat,
            })

    return items, merchant, finish_reason, total_tokens, remaining_tokens, reset_seconds


# A single Groq call reliably handles a receipt roughly this tall before it
# starts losing track or running out of its token budget (empirically: even
# a 1600px-tall, 60-item DMart bill only got 25-75% of its items in one shot,
# run to run). A fixed absolute strip size doesn't scale down well though —
# it left plenty of moderately-tall, still-dense bills (like that same DMart
# photo) under the split threshold entirely. Strip count now scales with the
# image's own height instead: split into ceil(h / TARGET) roughly-equal
# bands, so even a 1600px bill gets divided instead of only much taller ones.
# Tried lowering this to 550 (denser strips) hoping smaller/less dense
# crops would reduce hallucination. Live-tested twice on the same hard
# receipt: it didn't help — same 85-88% total accuracy as 900px, but
# consistently introduced a NEW failure (amounts shifted onto the wrong
# item, reproducible across both runs) and took ~2x longer (more strips =
# more rate-limit pacing). Reverted to 900, the better-measured config.
_TARGET_STRIP_HEIGHT = 900
_STRIP_OVERLAP = 160          # shared band between consecutive strips, so a
                               # line item straddling a cut still appears whole
                               # in at least one strip
_CHUNK_THRESHOLD = int(_TARGET_STRIP_HEIGHT * 1.3)
_MAX_STRIPS = 10              # bounds worst-case latency/cost on a corrupt
                               # or absurdly long image
# Rough cost of one more chunk request — if Groq reports less than this many
# tokens left in the current window, wait out the window before firing the
# next one rather than racing straight into a 429.
_TPM_CHUNK_SAFETY = 2500


def _split_image_into_strips(img) -> list:
    """Slice a tall receipt photo into overlapping horizontal bands at its
    ORIGINAL resolution (before any per-chunk downscale) — cropping first
    means each strip keeps far more legible detail than shrinking the whole
    multi-thousand-pixel photo down to fit in one request. Strip count scales
    with the image's own height so bands come out roughly evenly sized,
    rather than a fixed absolute strip size leaving an awkward sliver."""
    w, h = img.size
    if h <= _CHUNK_THRESHOLD:
        return [img]
    n_strips = min(_MAX_STRIPS, max(2, round(h / _TARGET_STRIP_HEIGHT)))
    step = -(-h // n_strips)  # ceil(h / n_strips): evenly-sized bands
    half_overlap = _STRIP_OVERLAP // 2
    strips = []
    for i in range(n_strips):
        band_top = i * step
        band_bottom = min(h, band_top + step)
        # Pad each band's edges into its neighbours' territory so a line
        # item sitting right on a cut still appears whole in this strip.
        top = max(0, band_top - half_overlap)
        bottom = min(h, band_bottom + half_overlap)
        strips.append(img.crop((0, top, w, bottom)))
        if band_bottom >= h:
            break
    return strips


def _normalize_desc(desc: str) -> str:
    """Strip digits/units/punctuation so 'Mccains French-420g' and
    'Mccains French' (or a garbled 'Eno'/'End') compare as the same item —
    a strip's overlap band gets read twice, often with the weight/size
    suffix dropped or a letter or two misread the second time."""
    only_letters = re.sub(r"[^a-z\s]", " ", desc.lower())
    return re.sub(r"\s+", " ", only_letters).strip()


def _is_likely_duplicate(a: str, b: str) -> bool:
    """Exact match, or one description is a prefix of the other (the real
    pattern seen on re-reads: the weight/size suffix gets dropped or added
    — "Mccains French-420g" vs "Mccains French"). Deliberately NOT a fuzzy
    character-similarity match: testing surfaced real false positives from
    that approach — "L Chana" vs "Dal Chana" (share "chana"), and "Mother Da
    Pro" vs "Mother Dairy St" (share a brand prefix, which is the norm on
    any grocery bill: "Amul X" / "Amul Y", "Tata X" / "Tata Y" are routinely
    different real products). A false match here silently drops a genuine
    purchase from someone's expense record — worse than a missed dedup,
    which just leaves one extra row the user can delete."""
    na, nb = _normalize_desc(a), _normalize_desc(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 4 and longer.startswith(shorter)


def _dedupe_boundary(prev_items: list, new_items: list, lookback: int = 15) -> list:
    """Drop items of `new_items` that are near-duplicates of an item near
    the tail of `prev_items` — the overlap band between two strips puts the
    same physical line item in both, and testing showed the re-read copies
    land scattered through the new chunk's output, not just at its very
    start, so every item is checked (not only a leading run). Matches on
    description similarity alone, not amount — the price is often exactly
    what differs between the two reads of the same line, so comparing it
    would miss the very duplicates this exists to catch. `lookback` is
    generous (15, not just a handful) since the overlap band can cover a
    meaningful chunk of a strip and the model doesn't necessarily list
    those lines first."""
    if not prev_items or not new_items:
        return new_items
    tail = prev_items[-lookback:]
    out = []
    for item in new_items:
        if any(_is_likely_duplicate(item["description"], t["description"]) for t in tail):
            continue
        out.append(item)
    return out


def _dedupe_self(items: list) -> list:
    """Drop items that are near-duplicates of an EARLIER item in the same
    response — on a dense enough strip the model can read through the whole
    visible list and then loop back, re-listing a slightly varied version of
    items it already gave (fabricated amount, shortened/garbled name)
    instead of stopping, all inside one response. `_dedupe_boundary` only
    catches duplicates across chunk boundaries; this catches the same
    failure happening within a single chunk's own output. Keeps the first
    occurrence of each distinct item."""
    kept: list = []
    for item in items:
        if any(_is_likely_duplicate(item["description"], k["description"]) for k in kept):
            continue
        kept.append(item)
    return kept


def _extract_with_groq_vision(file_bytes: bytes) -> list:
    """Send a receipt image to Groq Vision, get structured line items back.
    Tall/dense bills are sliced into overlapping strips and processed one at
    a time instead of one downscaled image the model loses track of partway
    through. Pacing between chunks is driven by Groq's own rate-limit
    headers (the account-wide authoritative state), not a local guess —
    each request still retries on 429 internally as the real safety net.
    """
    try:
        original = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    except Exception:
        items, merchant, *_ = _call_groq_vision_once(file_bytes)
        return items, merchant or "Unknown Merchant"

    strips = _split_image_into_strips(original)
    if len(strips) > 1:
        logger.info(f"OCR: bill is tall ({original.size[1]}px) — splitting into {len(strips)} strips")

    all_items: list = []
    merchant = None

    for idx, strip in enumerate(strips):
        buf = io.BytesIO()
        strip.save(buf, format="PNG")

        try:
            items, strip_merchant, finish_reason, tokens, remaining, reset_s = \
                _call_groq_vision_once(buf.getvalue())
        except httpx.HTTPStatusError as e:
            logger.warning(f"OCR chunk {idx + 1}/{len(strips)} failed: {e}")
            continue

        if strip_merchant and not merchant:
            merchant = strip_merchant

        items = _dedupe_self(items)
        deduped = _dedupe_boundary(all_items, items) if idx > 0 else items
        all_items.extend(deduped)
        logger.info(
            f"OCR chunk {idx + 1}/{len(strips)}: +{len(deduped)} items "
            f"(finish_reason={finish_reason}, {tokens} tokens, "
            f"{remaining} left in window)"
        )

        is_last = idx == len(strips) - 1
        if not is_last and remaining < _TPM_CHUNK_SAFETY:
            wait_for = reset_s + 1
            logger.info(f"OCR: only {remaining} tokens left in Groq's window — pacing {wait_for:.0f}s before next chunk")
            time.sleep(wait_for)

    return all_items, merchant or "Unknown Merchant"


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
            if settings.GOOGLE_CLOUD_CREDENTIALS not in ("", "{}"):
                from google.cloud import vision
                from google.oauth2 import service_account
                # Credentials are the full service-account JSON pasted as one
                # env var (same pattern as FIREBASE_SERVICE_ACCOUNT) — not a
                # file path, so ImageAnnotatorClient() with no args (which
                # only reads GOOGLE_APPLICATION_CREDENTIALS/ADC) won't pick
                # them up. Build the credentials object explicitly instead.
                creds_info = json.loads(settings.GOOGLE_CLOUD_CREDENTIALS)
                creds = service_account.Credentials.from_service_account_info(creds_info)
                client = vision.ImageAnnotatorClient(credentials=creds)
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
            except httpx.HTTPStatusError as e:
                logger.warning(f"Groq Vision failed: {e} — {e.response.text[:300]}")
                # This Groq org has an 8000 tokens-per-minute cap; one big-bill
                # scan can eat most of a minute's budget by itself. Surface
                # this distinctly — "could not read this receipt" would be
                # misleading when the real issue is "wait a bit and retry".
                if e.response.status_code in (413, 429):
                    raise HTTPException(
                        status_code=429,
                        detail="Our AI scanner is handling a lot of requests right now. Please wait about a minute and try scanning again.",
                    )
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
        # No provider produced anything (Google Vision unset/failed AND Groq
        # Vision returned no items) — fail loudly instead of returning a fake
        # amount=0.0/"Unknown Merchant" scan that looks like a successful read.
        if not raw_text:
            raise HTTPException(
                status_code=422,
                detail="Could not read this receipt. Try a clearer, well-lit photo.",
            )

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
