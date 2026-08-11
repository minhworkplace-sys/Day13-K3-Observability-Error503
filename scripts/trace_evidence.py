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
        response = client.get(f"{host}/api/public/traces", params=params)
        response.raise_for_status()
        return response.json().get("data", [])


def render(traces: list[dict]) -> str:
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
    return "\n".join(lines)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Evidence trace từ Langfuse")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--since-minutes", type=int, default=None)
    parser.add_argument("--session", default=None, help="Lọc theo session_id")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = render(fetch(args.limit, args.since_minutes, args.session))
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nĐã lưu: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
