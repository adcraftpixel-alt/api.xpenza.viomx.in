import re
from datetime import datetime
from typing import Optional


class SMSParser:

    # Bank SMS patterns (Indian banks)
    PATTERNS = [
        # HDFC debit
        {
            "regex": r"(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*)\s+(?:debited|deducted|spent).*?(?:at|to|for)\s+([A-Za-z0-9\s\.]+?)(?:\.|on|via|UPI|Ref|Avl)",
            "type": "debit"
        },
        # Generic: debited from account
        {
            "regex": r"(?:debited|debit)\s+(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*)\s+(?:at|to|from|for)\s+([A-Za-z0-9\s\.]+?)(?:\s+on|\s+via|\s+Ref|\.|$)",
            "type": "debit"
        },
        # UPI transfer
        {
            "regex": r"(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*)\s+(?:paid|transferred|sent)\s+(?:to|via)\s+([A-Za-z0-9\s@\.]+?)(?:\s+on|\s+Ref|\s+UPI|\.|$)",
            "type": "debit"
        },
        # Credit card
        {
            "regex": r"(?:transaction|txn)\s+(?:of\s+)?(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*)\s+(?:at|on)\s+([A-Za-z0-9\s\.]+?)(?:\s+on|\s+dated|\s+Ref|\.|$)",
            "type": "debit"
        },
        # SBI style
        {
            "regex": r"A/c\s+\w+\s+debited\s+(?:by|for)\s+(?:Rs\.?|INR)?\s*([\d,]+\.?\d*).*?(?:trf\s+to|info:\s+)([A-Za-z0-9\s/\.]+?)(?:\.|Ref|$)",
            "type": "debit"
        },
    ]

    def parse(self, sms_body: str) -> Optional[dict]:
        """Parse SMS and return expense dict or None"""
        sms_lower = sms_body.lower()

        # Skip credit/incoming transactions (unless also contains debit keyword)
        if any(w in sms_lower for w in ['credited', 'received', 'credit', 'cashback', 'refund']):
            if 'debit' not in sms_lower:
                return None

        for pattern_info in self.PATTERNS:
            match = re.search(pattern_info["regex"], sms_body, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    merchant = match.group(2).strip()[:50] if len(match.groups()) > 1 else "Unknown"

                    if amount <= 0 or amount > 10_000_000:
                        continue

                    # Extract date from SMS if present
                    date_match = re.search(r'(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', sms_body)
                    txn_date = date_match.group(1) if date_match else datetime.utcnow().strftime("%d/%m/%Y")

                    # Detect payment method
                    if 'upi' in sms_lower:
                        payment_method = 'upi'
                    elif any(w in sms_lower for w in ['credit card', 'cc ', 'card']):
                        payment_method = 'credit_card'
                    elif any(w in sms_lower for w in ['debit card', 'dc ']):
                        payment_method = 'debit_card'
                    else:
                        payment_method = 'bank'

                    return {
                        "amount": amount,
                        "merchant": merchant,
                        "date": txn_date,
                        "payment_method": payment_method,
                        "source": "sms",
                        "confidence": 0.85,
                        "raw_sms": sms_body[:200],
                    }
                except (ValueError, IndexError):
                    continue

        return None


sms_parser = SMSParser()
