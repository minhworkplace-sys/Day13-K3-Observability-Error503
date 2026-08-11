"""Dựng evidence PII redaction: đối chiếu input thô với log đã ghi.

    python scripts/pii_evidence.py

Xuất hai file vào submission/evidence/:

- pii-redaction.txt        — bảng "input thô -> log ghi ra" cho từng query có PII
- logs-pii-redacted.jsonl  — log thô của đúng những request đó

Đọc bảng này là thấy ngay: chuỗi PII trong input không còn xuất hiện ở bất kỳ đâu
trong log, kể cả trong payload lẫn trong user_id (chỉ còn user_id_hash).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

LOGS = REPO_ROOT / "data" / "logs.jsonl"
QUERIES = REPO_ROOT / "data" / "sample_queries.jsonl"
EVIDENCE = REPO_ROOT / "submission" / "evidence"

# Cùng bộ regex mà validate_logs.py dùng — quét độc lập với code redaction trong app/pii.py,
# nên nếu redaction hỏng thì bảng này lộ ra ngay chứ không tự khen mình.
PII_DETECTORS = {
    "email": re.compile(r"[\w.-]+@[\w.-]+\.\w+"),
    "phone_vn": re.compile(r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)"),
    "cccd": re.compile(r"\b\d{12}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
}


def detect(text: str) -> list[str]:
    return sorted(name for name, pattern in PII_DETECTORS.items() if pattern.search(text))


def main() -> int:
    configure_utf8_stdio()
    queries = [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with_pii = [query for query in queries if detect(query["message"])]
    if not with_pii:
        raise SystemExit("Không có query mẫu nào chứa PII.")

    records = [
        json.loads(line)
        for line in LOGS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    lines = [
        "Bằng chứng PII redaction",
        "",
        "Quét bằng chính bộ regex của validate_logs.py, độc lập với app/pii.py.",
        "",
        "Cột 'input thô' hiển thị nguyên văn để đối chiếu được trước/sau. Đây là dữ liệu",
        "mẫu tổng hợp của lab, đã có sẵn trong data/sample_queries.jsonl của repo gốc —",
        "không phải PII của người thật và không phải log của hệ thống.",
        "",
    ]
    leaks = 0
    kept: list[dict] = []

    for query in with_pii:
        session = query["session_id"]
        matching = [record for record in records if record.get("session_id") == session]
        kept.extend(matching)
        found = sorted({name for record in matching for name in detect(json.dumps(record, ensure_ascii=False))})
        leaks += len(found)
        preview = next(
            (
                record.get("payload", {}).get("message_preview")
                for record in matching
                if record.get("event") == "request_received"
            ),
            "(không tìm thấy log request_received)",
        )
        hashes = sorted({record.get("user_id_hash") for record in matching if record.get("user_id_hash")})
        lines += [
            f"[{session}] loại PII trong input: {', '.join(detect(query['message']))}",
            f"  input thô     : {query['message']}",
            f"  log ghi ra    : {preview}",
            f"  user_id       : {query['user_id']} -> user_id_hash={', '.join(hashes) or '-'}",
            f"  quét lại log  : {', '.join(found) if found else 'KHÔNG còn PII nào'}",
            "",
        ]

    lines.append(
        f"Tổng: {len(with_pii)} request có PII trong input, {len(kept)} log record liên quan, "
        f"{leaks} chuỗi PII còn sót."
    )
    lines.append(
        "user_id không bao giờ được ghi nguyên văn — chỉ có SHA-256 cắt 12 ký tự (app/pii.py:hash_user_id)."
    )

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines)
    (EVIDENCE / "pii-redaction.txt").write_text(report + "\n", encoding="utf-8")
    (EVIDENCE / "logs-pii-redacted.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in kept) + "\n",
        encoding="utf-8",
    )
    print(report)
    print("\nĐã lưu: submission/evidence/pii-redaction.txt, logs-pii-redacted.jsonl")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
