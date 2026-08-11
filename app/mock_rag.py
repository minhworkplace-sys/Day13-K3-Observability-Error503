from __future__ import annotations

import time

from .incidents import STATE
from .tracing import observe

CORPUS = {
    "refund": ["Refunds are available within 7 days with proof of purchase."],
    "monitoring": ["Metrics detect incidents, traces localize them, logs explain root cause."],
    "policy": ["Do not expose PII in logs. Use sanitized summaries only."],
}


# capture_input=False vì `message` là câu hỏi thô của người dùng, có thể chứa PII —
# log đã redact rồi thì trace cũng không được phép giữ bản chưa che.
@observe(name="rag_retrieve", as_type="retriever", capture_input=False, capture_output=False)
def retrieve(message: str) -> list[str]:
    if STATE["tool_fail"]:
        raise RuntimeError("Vector store timeout")
    if STATE["rag_slow"]:
        time.sleep(2.5)
    lowered = message.lower()
    for key, docs in CORPUS.items():
        if key in lowered:
            return docs
    return ["No domain document matched. Use general fallback answer."]
