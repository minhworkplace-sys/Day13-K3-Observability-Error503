from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

# Một correlation ID đến từ client là dữ liệu không tin cậy; chỉ nhận ID "sạch"
# để không ai chèn được ký tự lạ vào log qua header.
SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_correlation_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Mỗi request bắt đầu bằng context rỗng, tránh rò rỉ giữa các request.
        clear_contextvars()

        incoming = request.headers.get("x-request-id", "")
        correlation_id = incoming if SAFE_CORRELATION_ID.match(incoming) else new_correlation_id()

        # Từ đây mọi log trong request đều tự động mang correlation_id.
        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"

        return response
