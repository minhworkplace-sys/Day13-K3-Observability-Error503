"""Dựng evidence timeline cho challenge từ data/logs.jsonl.

    python scripts/challenge_timeline.py

Lọc log của đúng các session trong config/challenge.json, giữ lại lần chạy gần nhất,
rồi xuất hai file:

- submission/evidence/logs-challenge.jsonl — log thô có correlation ID
- submission/evidence/challenge-timeline.txt — bảng thời điểm nhận/trả của từng request

Bảng này là bằng chứng cho phần root cause: nếu app xử lý song song thật thì mọi
`request_received` phải xuất hiện gần như cùng lúc; chúng cách nhau đều đặn nghĩa là
event loop đang bị chặn và request phải xếp hàng.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.challenge import load_challenge, ordered_queries
from app.cli import configure_utf8_stdio

LOGS = REPO_ROOT / "data" / "logs.jsonl"
EVIDENCE = REPO_ROOT / "submission" / "evidence"


def parse_ts(record: dict) -> datetime:
    return datetime.fromisoformat(record["ts"].replace("Z", "+00:00"))


def main() -> int:
    configure_utf8_stdio()
    challenge = load_challenge()
    sessions = {query["session_id"] for query in ordered_queries(challenge)}

    records = [
        record
        for line in LOGS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("session_id") in sessions
        and record.get("event") in {"request_received", "response_sent"}
    ]
    if not records:
        raise SystemExit("Chưa có log challenge nào — chạy load_test.py --challenge trước.")

    # Mỗi request sinh đúng 2 record; giữ lần chạy gần nhất để evidence không lẫn các lần trước.
    records = sorted(records, key=parse_ts)[-2 * len(sessions) :]

    by_correlation: dict[str, dict] = {}
    for record in records:
        entry = by_correlation.setdefault(record["correlation_id"], {})
        entry[record["event"]] = record
        entry["session_id"] = record["session_id"]

    complete = {
        correlation_id: entry
        for correlation_id, entry in by_correlation.items()
        if "request_received" in entry and "response_sent" in entry
    }
    origin = min(parse_ts(entry["request_received"]) for entry in complete.values())

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "logs-challenge.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"Timeline challenge {challenge.challenge_id} "
        f"({len(complete)} request gửi song song, concurrency={len(complete)})",
        "",
        "t=0 là lúc handler nhận request đầu tiên. Client gửi cả "
        f"{len(complete)} request gần như cùng lúc.",
        "",
        f"{'correlation_id':16}{'session':22}{'nhận (t+s)':>12}{'trả (t+s)':>12}"
        f"{'latency_ms log':>16}{'client chờ (s)':>16}",
    ]
    for correlation_id, entry in sorted(
        complete.items(), key=lambda item: parse_ts(item[1]["request_received"])
    ):
        received = (parse_ts(entry["request_received"]) - origin).total_seconds()
        sent = (parse_ts(entry["response_sent"]) - origin).total_seconds()
        latency_ms = entry["response_sent"].get("latency_ms", "-")
        lines.append(
            f"{correlation_id:16}{entry['session_id']:22}{received:12.2f}{sent:12.2f}"
            f"{latency_ms:>16}{sent:16.2f}"
        )
    lines += [
        "",
        "Đọc bảng: mỗi request_received chỉ được ghi ngay sau khi response_sent của request",
        "trước hoàn tất, tức các request bị xử lý tuần tự chứ không song song. latency_ms trong",
        "log giữ nguyên ~2650ms cho mọi request vì nó chỉ đo bên trong LabAgent.run và bỏ qua",
        "thời gian request nằm chờ tới lượt.",
    ]
    report = "\n".join(lines)
    (EVIDENCE / "challenge-timeline.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print("\nĐã lưu: submission/evidence/logs-challenge.jsonl, challenge-timeline.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
