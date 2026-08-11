"""Liệt kê trace gần nhất trên Langfuse kèm prompt version — dùng làm evidence text.

    python scripts/trace_evidence.py --limit 20
    python scripts/trace_evidence.py --since-minutes 5 --out submission/evidence/traces-baseline.txt

In ra trace ID, session, tag và prompt_name/label/version/source đọc từ metadata mà
app/agent.py gắn vào trace. Không in nội dung câu hỏi để tránh đưa PII vào evidence.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from app.cli import configure_utf8_stdio

FIELDS = ("prompt_name", "prompt_label", "prompt_version", "prompt_source")


def fetch(limit: int, since_minutes: int | None, session: str | None = None) -> list[dict]:
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        raise SystemExit("Thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY trong .env")

    params: dict[str, object] = {"limit": limit, "orderBy": "timestamp.desc"}
    if session:
        params["sessionId"] = session
    if since_minutes:
        since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        params["fromTimestamp"] = since.isoformat().replace("+00:00", "Z")

    with httpx.Client(auth=(public, secret), timeout=30.0) as client:
        for attempt in range(5):
            response = client.get(f"{host}/api/public/traces", params=params)
            if response.status_code == 429:
                time.sleep(float(response.headers.get("retry-after") or 0) or 5 * 2**attempt)
                continue
            response.raise_for_status()
            return response.json().get("data", [])
    raise SystemExit("Langfuse chặn tần suất khi liệt kê trace; thử lại sau ít phút")


def fetch_observations(trace_id: str) -> list[dict]:
    """Đọc span con của một trace — chính là nội dung waterfall ở dạng text.

    Langfuse Cloud giới hạn tần suất gọi API, nên chờ và thử lại khi gặp 429 thay vì
    hỏng cả file evidence chỉ vì một request bị chặn.
    """
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    with httpx.Client(auth=auth, timeout=30.0) as client:
        for attempt in range(5):
            response = client.get(f"{host}/api/public/traces/{trace_id}")
            if response.status_code == 429:
                time.sleep(float(response.headers.get("retry-after") or 0) or 5 * 2**attempt)
                continue
            response.raise_for_status()
            observations = response.json().get("observations", [])
            return sorted(observations, key=lambda item: item.get("startTime") or "")
    raise SystemExit(f"Langfuse chặn tần suất khi đọc span của trace {trace_id}")


def render(traces: list[dict], with_spans: bool = False) -> str:
    if not traces:
        return "Không có trace nào trong khoảng thời gian đã chọn."

    lines = [f"{len(traces)} trace (mới nhất trước):", ""]
    for trace in traces:
        metadata = trace.get("metadata") or {}
        prompt = " ".join(f"{key}={metadata.get(key, '-')}" for key in FIELDS)
        tags = ",".join(trace.get("tags") or []) or "-"
        lines.append(
            f"- id={trace.get('id')}\n"
            f"  ts={trace.get('timestamp')}  name={trace.get('name')}\n"
            f"  user_id_hash={trace.get('userId')}  session={trace.get('sessionId')}  tags=[{tags}]\n"
            f"  latency={trace.get('latency')}  {prompt}"
        )
        if with_spans:
            for observation in fetch_observations(trace.get("id", "")):
                kind = observation.get("type", "?")
                name = observation.get("name", "?")
                latency = observation.get("latency")
                parent = "root" if not observation.get("parentObservationId") else "child"
                lines.append(f"    [{parent:5}] {kind:11} {name:34} latency={latency}s")
    return "\n".join(lines)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Evidence trace từ Langfuse")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--since-minutes", type=int, default=None)
    parser.add_argument("--session", default=None, help="Lọc theo session_id")
    parser.add_argument(
        "--spans",
        action="store_true",
        help="In kèm span con của từng trace (waterfall dạng text).",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = render(fetch(args.limit, args.since_minutes, args.session), with_spans=args.spans)
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nĐã lưu: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
