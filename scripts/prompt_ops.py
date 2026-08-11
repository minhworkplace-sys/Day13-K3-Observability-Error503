"""Quản lý prompt version trên Langfuse cho Checkpoint 2.

    python scripts/prompt_ops.py setup     # tạo v1 (baseline+production) và v2 (candidate)
    python scripts/prompt_ops.py list      # in version + label hiện tại (dùng làm evidence text)
    python scripts/prompt_ops.py label --version 2 --labels production   # promote
    python scripts/prompt_ops.py label --version 1 --labels production   # rollback

Prompt giữ nguyên ba biến {{feature}}, {{docs}}, {{message}} theo contract trong
docs/PROMPT_VERSIONING.md; app đọc prompt qua LANGFUSE_PROMPT_NAME/LABEL.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from app.cli import configure_utf8_stdio
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE

# v2 chỉ khác v1 một chỉ dẫn về format/độ dài — đủ để phân biệt version, không phải bài tối ưu prompt.
CANDIDATE_TEMPLATE = (
    DEFAULT_PROMPT_TEMPLATE
    + "\n\nAnswer in at most 3 sentences and name the doc you used."
)


def client():
    from langfuse import get_client

    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        raise SystemExit("Thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY trong .env")
    return get_client()


def prompt_name() -> str:
    return os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")


def existing_versions(lf, name: str) -> list[dict]:
    page = lf.api.prompts.list(name=name)
    out: list[dict] = []
    for meta in page.data:
        labels_by_version = getattr(meta, "labels", []) or []
        for version in getattr(meta, "versions", []) or []:
            out.append({"version": version, "labels": labels_by_version})
    return out


def cmd_list(lf, name: str) -> int:
    page = lf.api.prompts.list(name=name)
    if not page.data:
        print(f"Chưa có prompt nào tên '{name}'. Chạy: python scripts/prompt_ops.py setup")
        return 1
    for meta in page.data:
        print(f"prompt: {meta.name}")
        for version in sorted(getattr(meta, "versions", []) or []):
            detail = lf.api.prompts.get(prompt_name=name, version=version)
            labels = ", ".join(sorted(detail.labels or [])) or "(không label)"
            first_line = (detail.prompt or "").splitlines()[0] if detail.prompt else ""
            print(f"  v{version}  labels=[{labels}]  dòng đầu: {first_line}")
    return 0


def cmd_setup(lf, name: str) -> int:
    versions = {v["version"] for v in existing_versions(lf, name)}
    if versions:
        print(f"'{name}' đã có version {sorted(versions)}; không tạo lại để tránh đẻ thêm version.")
        return cmd_list(lf, name)

    v1 = lf.create_prompt(
        name=name,
        prompt=DEFAULT_PROMPT_TEMPLATE,
        type="text",
        labels=["baseline", "production"],
        commit_message="v1 baseline: template gốc của lab",
    )
    print(f"Đã tạo v{v1.version} labels=[baseline, production]")

    v2 = lf.create_prompt(
        name=name,
        prompt=CANDIDATE_TEMPLATE,
        type="text",
        labels=["candidate"],
        commit_message="v2 candidate: giới hạn 3 câu và yêu cầu nêu tên doc",
    )
    print(f"Đã tạo v{v2.version} labels=[candidate]")
    return cmd_list(lf, name)


def cmd_label(lf, name: str, version: int, labels: list[str]) -> int:
    lf.update_prompt(name=name, version=version, new_labels=labels)
    print(f"Đã gán label {labels} cho {name} v{version}")
    return cmd_list(lf, name)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Prompt versioning trên Langfuse")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Tạo v1 (baseline+production) và v2 (candidate)")
    sub.add_parser("list", help="In version và label hiện tại")
    label = sub.add_parser("label", help="Gán label cho một version (promote hoặc rollback)")
    label.add_argument("--version", type=int, required=True)
    label.add_argument("--labels", nargs="+", required=True)
    args = parser.parse_args()

    lf = client()
    name = prompt_name()
    if args.command == "setup":
        return cmd_setup(lf, name)
    if args.command == "list":
        return cmd_list(lf, name)
    return cmd_label(lf, name, args.version, args.labels)


if __name__ == "__main__":
    raise SystemExit(main())
