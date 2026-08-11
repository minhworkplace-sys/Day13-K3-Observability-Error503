from __future__ import annotations

import hashlib
import re

# Thứ tự có ý nghĩa: pattern dài/cụ thể chạy trước để không bị pattern ngắn cắt vụn.
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "cccd": r"\b\d{12}\b",
    # Hộ chiếu VN: 1 chữ cái + 7 chữ số, ví dụ B1234567.
    "passport_vn": r"\b[A-Z]\d{7}\b",
    # Địa chỉ VN: số nhà + từ khoá đơn vị hành chính, ví dụ "số 12 đường Láng, quận Đống Đa".
    "address_vn": (
        r"(?i)\b(?:số\s*)?\d{1,4}(?:/\d{1,4})*\s+"
        r"(?:đường|phố|ngõ|hẻm|ấp|thôn|khu\s*phố|phường|xã|quận|huyện|tỉnh|tp\.?|thành\s*phố)"
        r"\s+[^\n,.;]{1,40}"
    ),
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
