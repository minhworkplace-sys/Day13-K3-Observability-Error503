# Mục lục evidence

Đối chiếu với checklist bắt buộc trong [SUBMISSION.md](../../SUBMISSION.md). Mọi file text/JSON/HTML đều dựng lại được bằng script trong `scripts/` (xem phụ lục của [REPORT.md](../REPORT.md)).

| # | Yêu cầu | File | Trạng thái |
|---|---|---|---|
| 1 | Kết quả `validate_logs.py` cuối cùng | `validate-logs.txt` | ✅ 100/100 — 153 record, 77 correlation ID, 0 PII leak |
| 2 | Danh sách ≥ 10 traces | `traces-recent.txt` | ✅ 20 trace, đủ metadata, `prompt_source=langfuse` |
| 3 | Một trace waterfall đầy đủ | `trace-waterfall.txt` + ⬜ `trace-waterfall.png` | ⚠️ bản text đã đủ số liệu; còn thiếu ảnh chụp |
| 4 | Log JSON có correlation ID và metadata | `logs-challenge.jsonl` | ✅ mỗi cặp `request_received`/`response_sent` dùng chung `correlation_id`, kèm `user_id_hash`/`session_id`/`feature`/`model`/`env` |
| 5 | Log chứng minh PII đã redact | `pii-redaction.txt`, `logs-pii-redacted.jsonl` | ✅ 3 loại PII (email, phone VN, thẻ), 0 chuỗi còn sót |
| 6 | Dashboard đủ 6 nhóm chỉ số | `dashboard.html`, `dashboard-baseline.html`, `validate-dashboard.txt` | ✅ 6/6 panel; có bản trước và sau sự cố |
| 7 | Alert rules và runbook | `alert_rules.yaml`, `alerts-runbook.md`, `slo.yaml` | ✅ 4 alert, mỗi alert có SLO, ngưỡng, 3 bước kiểm tra, mitigation và owner |
| 8 | Evidence điều tra challenge | `metrics-baseline.json`, `metrics-incident.json`, `metrics-comparison.json`, `challenge-timeline.txt`, `traces-challenge.txt`, `trace-waterfall.txt` | ⚠️ đủ số liệu; còn thiếu ảnh chụp dashboard |
| — | Prompt v1/v2 và bằng chứng rollback | `traces-prompt-versions.txt` | ⚠️ đủ trace ID; còn thiếu ảnh chụp màn hình Langfuse |
| — | Evidence checkpoint 0 và 1 | `health.png`, `cp1.png` | ✅ |

## Luồng đọc theo Metrics → Traces → Logs

1. **Metrics** — `metrics-comparison.json`: p95 nhảy từ 153 ms lên 2.652 ms (+2.499 ms) trong khi p50 đứng yên 152 ms và `error_breakdown` rỗng. Chậm ở phần đuôi, không phải lỗi.
2. **Traces** — `trace-waterfall.txt`: trong 2,656s của trace, span `rag_retrieve` chiếm 2,503s (94,2%), `llm_generate` chỉ 0,151s. Trace đối chứng lúc incident tắt có `rag_retrieve` = 0,000s.
3. **Logs** — `challenge-timeline.txt`: 5 request gửi song song nhưng bị xử lý tuần tự, cách nhau đúng 2,65s, request cuối chờ 13,30s trong khi log chỉ ghi `latency_ms=2652`.

Kết luận và fix nằm ở mục 6 của [REPORT.md](../REPORT.md).

## Ảnh còn thiếu

`trace-waterfall.png`, `prompt-versions.png`, `prompt-label-rollback.png`, `dashboard.png`, `dashboard-baseline.png` — xem mục 8 của [REPORT.md](../REPORT.md) để biết chụp ở đâu.

## Lưu ý cho người chấm

Toàn bộ trace ID trong evidence thuộc project Langfuse `cmso2fy6e03umad0cv9huvgox`. Mở bằng cặp key khác sẽ trả về 404 chứ không phải trace không tồn tại.
