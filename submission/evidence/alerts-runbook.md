# Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Định nghĩa chính thức của điều kiện nằm trong [`config/alert_rules.yaml`](../config/alert_rules.yaml); mục tiêu nằm trong [`config/slo.yaml`](../config/slo.yaml). Nguồn dữ liệu của cả bốn alert là `data/logs.jsonl`, cùng field với sáu panel trong [`config/dashboard.yaml`](../config/dashboard.yaml).

Luồng xử lý chung cho mọi alert: **Metrics → Traces → Logs**. Lấy khung giờ từ metrics, mở trace trong khung giờ đó để khoanh vùng span bất thường, rồi dùng `correlation_id` để tìm log chứng minh nguyên nhân.

## Alert 1

- Tên: `chat_latency_p95_slo_breach`
- Severity: high
- SLI/SLO liên quan: `latency_p95_ms` — 99.5% cửa sổ 28 ngày giữ p95 ≤ 3000ms
- Điều kiện và thời gian duy trì: p95(`latency_ms`) của `response_sent` > 3000ms, duy trì 5 phút, tối thiểu 20 request trong cửa sổ (ngưỡng số lượng để một vài request lẻ không tạo báo động giả)
- Ảnh hưởng tới người dùng: người dùng chờ quá 3 giây mỗi câu trả lời; client đặt timeout ngắn có thể bỏ request giữa chừng
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Latency percentiles**, so p50 với p95. p50 tăng cùng p95 nghĩa là chậm toàn hệ thống; chỉ p95 tăng nghĩa là chậm ở phần đuôi hoặc chỉ một `feature`.
  2. Mở panel **Request traffic** để loại trừ nguyên nhân tăng tải, rồi lọc log theo `feature` để xem sự cố chỉ xảy ra ở một feature hay tất cả.
  3. Mở một trace chậm trên Langfuse, xem span nào chiếm phần lớn thời gian (retrieval hay generation), rồi lấy `correlation_id` của trace đó tìm cặp log `request_received`/`response_sent` tương ứng.
- Mitigation tạm thời: nếu chậm nằm ở retrieval, tắt/bypass bước retrieval cho feature bị ảnh hưởng và trả lời bằng fallback; nếu vừa đổi prompt, rollback label `production` về version trước.
- Owner: vai trò Dashboard, SLO & Alert

## Alert 2

- Tên: `chat_error_rate_slo_breach`
- Severity: critical
- SLI/SLO liên quan: `error_rate_pct` — 99.0% cửa sổ 28 ngày giữ error rate ≤ 2%
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received)` > 2%, duy trì 10 phút, tối thiểu 20 request trong cửa sổ
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 và không có câu trả lời; đây là lỗi thấy được trực tiếp nên để severity cao nhất
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Error rate and breakdown**, đọc `error_type` chiếm đa số (ví dụ `RuntimeError` từ vector store timeout).
  2. Kiểm tra `GET /health` xem có incident nào đang bật trong `incidents` không.
  3. Lọc log `event == "request_failed"`, lấy `correlation_id` và đọc `payload.detail` để biết dependency nào hỏng.
- Mitigation tạm thời: tắt incident/dependency đang lỗi (`python scripts/inject_incident.py --scenario <tên> --disable`), hoặc cho retrieval trả về fallback thay vì raise để request vẫn có câu trả lời giảm chất lượng thay vì lỗi hẳn.
- Owner: vai trò Incident, Report & Demo

## Alert 3

- Tên: `chat_quality_proxy_drop`
- Severity: warning
- SLI/SLO liên quan: `quality_score_avg` — 95% cửa sổ 28 ngày giữ mean ≥ 0.75
- Điều kiện và thời gian duy trì: mean(`quality_score`) của `response_sent` < 0.75, duy trì 15 phút, tối thiểu 30 request trong cửa sổ (quality proxy nhiễu hơn latency nên cần cửa sổ dài và nhiều mẫu hơn)
- Ảnh hưởng tới người dùng: hệ thống vẫn trả lời và vẫn nhanh, nhưng câu trả lời mất ngữ cảnh retrieval hoặc bị cắt ngắn — lỗi âm thầm mà latency và error rate không phát hiện được
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Quality proxy** và đối chiếu thời điểm giảm với lần đổi label prompt gần nhất.
  2. Mở hai trace trước/sau thời điểm đó, so `prompt_version` và `prompt_label` trong metadata.
  3. Kiểm tra `prompt_source` trong metadata trace: nếu là `local-fallback` thì app đang không lấy được prompt managed và đã âm thầm chạy template local.
- Mitigation tạm thời: rollback label `production` về version prompt trước đó; nếu `prompt_source=local-fallback` thì kiểm tra `LANGFUSE_HOST`/key và khôi phục kết nối Langfuse.
- Owner: vai trò Tracing & Prompt Version

## Alert 4

- Tên: `chat_daily_cost_budget_burn`
- Severity: warning
- SLI/SLO liên quan: `daily_cost_usd` — ngân sách 2.5 USD/ngày
- Điều kiện và thời gian duy trì: `sum(cost_usd)` tính từ 00:00 UTC vượt 2.0 USD, tức 80% ngân sách; cảnh báo sớm để còn thời gian xử lý trước khi thủng ngân sách
- Ảnh hưởng tới người dùng: chưa ảnh hưởng ngay, nhưng nếu chạm hạn mức nhà cung cấp thì request sẽ bị từ chối — rủi ro về chi phí và về khả năng phục vụ
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Cost over time**, xác định chi phí tăng đều hay nhảy bậc tại một thời điểm.
  2. Đối chiếu panel **Input and output tokens** với panel **Request traffic**: traffic tăng là do dùng nhiều, còn traffic phẳng mà token tăng là do mỗi câu trả lời dài ra bất thường.
  3. So `tokens_out` trung bình trước và sau thời điểm nhảy bậc, rồi kiểm tra thay đổi prompt hoặc `max_tokens` gần nhất.
- Mitigation tạm thời: đặt trần `max_tokens` cho output, rollback prompt version làm câu trả lời dài ra, và bật rate limit theo `user_id_hash` cho các phiên gọi bất thường.
- Owner: vai trò Dashboard, SLO & Alert
