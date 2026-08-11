# Báo cáo Day 13 Observability

> Các dòng đánh dấu ⬜ là phần còn phải tự làm: ảnh chụp màn hình (gom đủ ở [mục 8](#8-checklist-ảnh-chụp-còn-thiếu)) và cột "Điều đã học" của từng thành viên.
> Mọi số liệu còn lại trong báo cáo đều lấy từ file trong `submission/evidence/` và có thể kiểm chứng lại.

## 1. Thông tin nhóm

- Tên nhóm: Error503
- Repository URL: https://github.com/minhworkplace-sys/Day13-K3-Observability-Error503
- Commit SHA cuối: nhánh `HoangMinh`; commit chứa bản report này là `61cea5a` ("docs: hoàn thiện checkpoint 3 và REPORT.md"). Trước khi nộp lên Codelabs, lấy SHA đầy đủ của commit cuối cùng bằng `git rev-parse HEAD` (sẽ đổi nếu còn commit thêm ảnh chụp ở mục 8).
- Thành viên và vai trò: 
Nguyễn Hoàng Minh	2A202601229 QA
Nguyễn Gia Thiều	2A202601759 Backend Engineer
Nguyễn Quốc Thịnh	2A202601675 SRE & Alerts Engineer

## 2. Kết quả kỹ thuật

| Hạng mục | Kết quả | Evidence |
|---|---|---|
| `validate_logs.py` | **100/100** — 78 record, 35 correlation ID, 0 thiếu field, 0 PII leak | `evidence/validate-logs.txt` |
| `validate_dashboard.py` | **HỢP LỆ: 6/6 panel** | `evidence/validate-dashboard.txt` |
| Traces trên Langfuse | **29 trace** có metadata (10 baseline + 4 prompt version + 10 baseline lần 2 + 5 challenge) | `evidence/traces-baseline.txt` (10 trace), `evidence/traces-prompt-versions.txt` (4), `evidence/traces-challenge.txt` (6) |
| PII leak còn lại | **0** | `evidence/validate-logs.txt` |
| Dashboard | `evidence/dashboard.html` (mở bằng trình duyệt), bản trước sự cố ở `evidence/dashboard-baseline.html` | `evidence/dashboard*.html` |
| Public tests | 22 passed | `python -m pytest -q` |

Môi trường: Python 3.11.9, Langfuse Cloud (`https://cloud.langfuse.com`), fake LLM nên không tốn API key trả phí.

## 3. Logging và tracing

**Correlation ID** — `app/middleware.py` sinh ID dạng `req-<8 hex>` cho mỗi request, hoặc nhận lại `x-request-id` của client nếu ID đó khớp `^[A-Za-z0-9._-]{1,64}$` (ID từ client là dữ liệu không tin cậy, không cho ký tự lạ chui vào log). ID được `bind_contextvars` nên mọi log trong request tự mang theo, và trả về client qua header `x-request-id` + `x-response-time-ms`. Đầu mỗi request gọi `clear_contextvars()` để context không rò rỉ sang request khác.

- Evidence correlation ID: `evidence/logs-challenge.jsonl` — mỗi cặp `request_received`/`response_sent` dùng chung một `correlation_id`, ví dụ `req-76c95062`.

**Metadata** — `app/main.py` bind `user_id_hash`, `session_id`, `feature`, `model`, `env` cho toàn bộ log của request. `user_id` không bao giờ được ghi nguyên văn, chỉ ghi SHA-256 cắt 12 ký tự (`hash_user_id`).

**PII redaction** — `scrub_event` được đăng ký trong pipeline `structlog` **trước** processor ghi file, nên dữ liệu chưa che không bao giờ chạm đĩa. Pattern trong `app/pii.py`: email, thẻ tín dụng, số điện thoại VN (5 định dạng), CCCD 12 số, hộ chiếu VN, địa chỉ VN theo số nhà + từ khoá hành chính.

- Evidence PII redaction: log của `u01` (input có `student@vinuni.edu.vn`) ghi `message_preview` thành `[REDACTED_EMAIL]`; `u05` (`0987654321`) và `u09` (thẻ `4111 1111 1111 1111`) tương tự. `validate_logs.py` quét PII bằng regex độc lập với code redaction và báo 0 leak.
- Evidence trace waterfall: ⬜ ảnh chụp một trace trên Langfuse (mở bất kỳ trace ID nào trong `evidence/traces-challenge.txt`).

**Một span đáng chú ý** — trace `f5c38deff56a53029bbf4dea5c6eaa49` (session `k3-challenge-s03`) báo `latency=2.652s`, trong đó ~2.5s nằm ở bước retrieval và ~0.15s ở generation. Nhưng client gửi request này phải chờ **13.28s**. Khoảng chênh 10.6s không nằm trong bất kỳ span nào — đó chính là manh mối của phần 6.

## 4. Prompt versioning

- Prompt name: `day13-chat` (text prompt, giữ ba biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- Version/label baseline: **v1** — labels `baseline`, `production`. Nội dung: template gốc của lab.
- Version/label candidate: **v2** — label `candidate`. Khác v1 đúng một dòng: `Answer in at most 3 sentences and name the doc you used.`

Cả hai version được tạo bằng `scripts/prompt_ops.py setup` (script của nhóm, dùng Langfuse SDK). Chạy lại `setup` sẽ không đẻ thêm version.

**Trace ID của mỗi version** — bốn trace dưới đây dùng **cùng một input** (`session_id=prompt-version-compare`, feature `policy`), chỉ khác label:

| Bước | Label khi chạy | Version thực tế | Trace ID |
|---|---|---|---|
| 1. Baseline | `baseline` | v1 | `5ce0000998e2f2ee528bd525fa156154` |
| 2. Candidate | `candidate` | v2 | `47c4e2aab5e0e5ecaee39b10b38e1a50` |
| 3. Sau khi promote | `production` | **v2** | `e9ce5109aba9fce1ff2b57261900dd54` |
| 4. Sau khi rollback | `production` | **v1** | `d2111531d23f42988f9cc63f67f71bd7` |

Cả bốn trace đều có `prompt_source=langfuse` — tức app thật sự lấy prompt managed chứ không rơi về template local.

**Bằng chứng đổi label và rollback** — hai trace cuối chứng minh vòng promote → rollback:

```bash
python scripts/prompt_ops.py label --version 2 --labels production candidate   # promote
python scripts/prompt_ops.py label --version 1 --labels production baseline    # rollback
```

Trạng thái label sau khi rollback: `v1 = [baseline, production]`, `v2 = [candidate, latest]`.

- Evidence text: `evidence/traces-prompt-versions.txt`
- ⬜ Ảnh danh sách hai prompt version trên Langfuse
- ⬜ Ảnh trước/sau khi đổi label `production`

## 5. Dashboard, SLO và alerts

**Kết quả validator**: `HỢP LỆ: 6/6 panel có trong dashboard contract.` (`evidence/validate-dashboard.txt`)

**Dashboard** — `scripts/render_dashboard.py` đọc `config/dashboard.yaml` rồi dựng đúng sáu panel từ `data/logs.jsonl`. Script không hard-code giá trị panel nào: event, field, phép tổng hợp, đơn vị và threshold đều lấy từ contract, nên sửa contract là dashboard đổi theo. Kết quả trong cửa sổ 60 phút của lần chạy cuối:

| Panel | Giá trị đo | Threshold | Trạng thái |
|---|---|---|---|
| latency | p95 = 2.651 ms | p95 ≤ 3.000 ms | đạt |
| traffic | 3,30 req/phút | rate ≥ 1/phút | đạt |
| errors | 0,00% | ≤ 2% | đạt |
| cost | $0,0679 | tổng ≤ $2,5 | đạt |
| tokens | 4.287 | mỗi field ≤ 50.000 | đạt |
| quality | 0,858 | mean ≥ 0,75 | đạt |

- Evidence dashboard: `evidence/dashboard.html` và `evidence/dashboard-baseline.html`. ⬜ Chụp màn hình cả hai (đã hiện sẵn tên panel, time range 60 phút, refresh 30s, đơn vị và threshold).

**SLO đã chọn và lý do** (`config/slo.yaml`) — bốn SLI bám đúng bốn nhóm rủi ro khác nhau: latency p95 ≤ 3000ms (trải nghiệm chờ), error rate ≤ 2% (lỗi thấy được), cost ≤ $2,5/ngày (ngân sách), quality mean ≥ 0,75 (lỗi âm thầm mà hai chỉ số đầu không bắt được). Baseline đo được p95 ≈ 1.255 ms nên ngưỡng 3.000 ms còn rất nhiều dư địa; đây là lựa chọn có chủ ý để alert chỉ kêu khi thực sự bất thường.

**Alert rules và runbook** (`config/alert_rules.yaml` + `docs/alerts.md`) — bốn alert, tất cả đều dựa trên triệu chứng người dùng hoặc SLO, không dựa vào tên hàm nội bộ:

| Alert | Severity | Điều kiện |
|---|---|---|
| `chat_latency_p95_slo_breach` | high | p95 > 3000ms, giữ 5 phút, ≥ 20 request |
| `chat_error_rate_slo_breach` | critical | error rate > 2%, giữ 10 phút, ≥ 20 request |
| `chat_quality_proxy_drop` | warning | mean(quality) < 0,75, giữ 15 phút, ≥ 30 request |
| `chat_daily_cost_budget_burn` | warning | cost từ 00:00 UTC > $2,0 (80% ngân sách) |

Mỗi alert có ngưỡng số lượng request tối thiểu để vài request lẻ không tạo báo động giả, và mỗi alert có runbook riêng trong `docs/alerts.md` gồm ba bước kiểm tra đầu tiên, mitigation tạm thời và owner.

## 6. Điều tra challenge

- **Challenge ID**: `day13-k3-observability-v1` (cohort K3, incident `rag_slow`, feature `refund`, seed 1303, `latency_threshold_ms = 2000`)
- Input chính thức: 5 query trong `config/challenge.json` (session `k3-challenge-s01`…`s05`). File này **không bị sửa**.
- Lệnh đã chạy: `python scripts/inject_incident.py` rồi `python scripts/load_test.py --challenge --concurrency 5`

**Kết luận một dòng**: incident `rag_slow` thêm 2,5s vào bước retrieval; lỗi kiến trúc `async def` gọi hàm đồng bộ biến 2,5s đó thành 13,3s ở phía người dùng, đồng thời cách đo latency hiện tại giấu toàn bộ phần khuếch đại này khỏi dashboard và alert.

Năm mục dưới đây bám đúng năm bước của Checkpoint 3: chạy incident → triệu chứng từ metrics → khoanh vùng span → chứng minh bằng log → fix và phòng ngừa.

### Triệu chứng từ metrics

`/metrics` trước và sau khi bật incident (`evidence/metrics-baseline.json`, `evidence/metrics-incident.json`):

| Chỉ số | Baseline | Trong sự cố |
|---|---|---|
| latency_p50 | 150 ms | 151 ms |
| **latency_p95** | **1.255 ms** | **2.651 ms** |
| traffic | 10 | 15 |
| error_breakdown | {} | {} |
| quality_avg | 0,88 | 0,873 |

p50 gần như không đổi còn p95 tăng gấp đôi — dấu hiệu kinh điển của chậm ở phần đuôi, chỉ một nhóm request bị ảnh hưởng chứ không phải cả hệ thống. Không có lỗi nào (`error_breakdown` rỗng ở cả hai lần đo) và quality gần như không đổi (0,88 → 0,873), nên đây là sự cố latency thuần tuý chứ không phải lỗi chất lượng hay lỗi tool. Nhóm request bị ảnh hưởng chính là feature `refund` — đúng `affected_feature` mà challenge khai báo.

p95 = 2.651 ms đã vượt `latency_threshold_ms = 2000` của challenge, nhưng **vẫn dưới SLO 3.000 ms của nhóm** — chi tiết này quay lại ở phần root cause.

**Nhưng client lại đo được 7,9s đến 13,3s** cho chính năm request đó. Chênh lệch giữa 2,65s mà server báo và 13,3s mà người dùng chịu chính là phần đáng điều tra nhất.

### Trace: khoanh vùng span bất thường

Năm trace của challenge (`evidence/traces-challenge.txt`), nối với log qua `session_id`:

| Session | Trace ID | Latency trong trace |
|---|---|---|
| k3-challenge-s01 | `5c4de1479babb4f4072f0cbdad295e25` | 2,652s |
| k3-challenge-s02 | `fe7c3c8c5cad2d078d6e435f781f9197` | 2,652s |
| k3-challenge-s03 | `f5c38deff56a53029bbf4dea5c6eaa49` | 2,652s |
| k3-challenge-s04 | `d200a032cc24d320a05d5db4a743fa19` | 2,652s |
| k3-challenge-s05 | `0589847e0183a9bfb085e90945192309` | 2,652s |

Cả năm trace **giống hệt nhau ở 2,652s**, trong đó bước retrieval chiếm ~2,5s còn generation ~0,15s. Trace chỉ ra bước retrieval là nơi phát sinh độ trễ, nhưng không giải thích được vì sao request cuối phải chờ 13,3s — vì phần chờ đó xảy ra **trước khi** trace được tạo.

### Log: chứng minh root cause

`evidence/challenge-timeline.txt`, dựng từ `evidence/logs-challenge.jsonl`:

```
correlation_id  session               nhận (t+s)   trả (t+s)  latency_ms log  client chờ (s)
req-76c95062    k3-challenge-s02            0.00        2.65            2651            2.65
req-965143c8    k3-challenge-s01            2.66        5.31            2651            5.31
req-e36f3059    k3-challenge-s05            5.31        7.96            2651            7.96
req-c74c74a2    k3-challenge-s04            7.97       10.62            2651           10.62
req-101a0b2f    k3-challenge-s03           10.63       13.28            2651           13.28
```

Năm request được client gửi song song, nhưng log `request_received` của mỗi request chỉ được ghi **đúng vào lúc** request trước ghi `response_sent`. Chúng bị xử lý tuần tự, mỗi lượt cách nhau đúng 2,65s.

### Root cause

Hai nguyên nhân chồng lên nhau:

1. **Nguyên nhân trực tiếp** — incident `rag_slow` thêm `time.sleep(2.5)` vào `mock_rag.retrieve()`, làm mỗi request chậm thêm 2,5s.
2. **Nguyên nhân khuếch đại (lỗi kiến trúc)** — `app/main.py` khai báo endpoint `async def chat`, nhưng bên trong gọi thẳng `agent.run()` là hàm **đồng bộ**. Một lệnh `time.sleep()` đồng bộ trong endpoint `async` sẽ chặn cả event loop, nên toàn bộ request khác phải xếp hàng. Đây là head-of-line blocking: sự cố 2,5s bị nhân lên thành 13,3s ở concurrency 5, và sẽ tệ tuyến tính theo số request đồng thời.

Bằng chứng cho điểm 2 nằm ở cột "nhận (t+s)": nếu app xử lý song song đúng nghĩa, cả năm `request_received` phải được ghi gần như cùng lúc và cả năm request cùng xong sau ~2,65s. Việc chúng cách nhau đều đặn 2,65s chỉ có thể xảy ra khi event loop bị chặn.

**Điểm mù quan sát đi kèm** — `latency_ms` được đo bên trong `LabAgent.run`, tức chỉ tính từ lúc request giành được event loop. Nó bỏ qua toàn bộ thời gian xếp hàng. Hệ quả trực tiếp: dashboard báo p95 = 2.651 ms, **vẫn dưới SLO 3.000 ms**, nên `chat_latency_p95_slo_breach` sẽ **không kêu** trong khi người dùng đang chờ 13 giây. Sự cố này lẽ ra lọt lưới hoàn toàn.

### Fix action

1. Bỏ chặn event loop — đổi `async def chat` thành `def chat` (FastAPI sẽ tự chạy trong threadpool), hoặc giữ `async` và bọc `await run_in_threadpool(agent.run, ...)`. Sửa xong, năm request đồng thời cùng xong sau ~2,65s thay vì 13,3s.
2. Tắt incident retrieval: `python scripts/inject_incident.py --disable` (đã chạy, `/health` xác nhận `rag_slow: false`).
3. Đặt timeout cho bước retrieval và trả fallback khi quá hạn, để một dependency chậm không kéo theo toàn bộ request.

### Preventive measure

1. **Đo latency ở rìa ngoài, không đo ở lõi.** Middleware đã tính `x-response-time-ms` bao trọn thời gian xếp hàng — đưa số này vào log và cho panel latency dùng nó. Đây là phần vá đúng điểm mù đã nêu.
2. **Thêm một SLI hàng đợi** (thời gian từ lúc nhận kết nối tới lúc handler chạy) kèm alert riêng, vì error rate và latency lõi đều không nhìn thấy hiện tượng này.
3. **Ghi `correlation_id` vào metadata của trace.** Hiện Metrics → Traces → Logs phải nối qua `session_id`; có `correlation_id` trong trace thì nối được trực tiếp một–một.
4. **Test tải hồi quy có concurrency > 1** trong CI, chốt ngưỡng p95 đo từ phía client — bài này chỉ lộ ra khi chạy song song.
5. **Chặn `time.sleep` và I/O đồng bộ trong đường async** bằng lint rule hoặc `asyncio` debug mode, để lỗi kiến trúc này không tái diễn.

## 7. Đóng góp cá nhân

Bảng dưới được dựng từ `git log --all`; tài khoản Git được map sang tên thật như sau — **mỗi thành viên kiểm tra lại dòng của mình trước khi nộp**, cột "Điều đã học" phải tự viết.

| Thành viên | Tài khoản Git | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|---|
| Nguyễn Hoàng Minh (QA) | `Hoàng Minh` / minhworkplace@gmail.com | Setup baseline và evidence checkpoint 0 (`health.png`); chạy validator; tổng hợp và viết `submission/REPORT.md`; merge nhánh của các thành viên | `39d6a99` (CP0), `709ff3d` (merge `origin/Thinh`), `85089ae` + commit cuối (report) | ⬜ |
| Nguyễn Gia Thiều (Backend Engineer) | `thieunguyen879` | Checkpoint 1: logging JSON, correlation ID middleware, enrichment metadata, PII redaction; instrument trace trong `app/agent.py`; incident hook `mock_rag` | `bf5c68a` (cp1), `caa0fd2` (evidence cp1.png), `f60d13c` (merge) | ⬜ |
| Nguyễn Quốc Thịnh (SRE & Alerts Engineer) | `ngthomas562-hub` | Checkpoint 2 và 3: `scripts/render_dashboard.py`, `scripts/prompt_ops.py`, `scripts/trace_evidence.py`; `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`; thu thập toàn bộ evidence challenge | `307ebd9` | ⬜ |

Các commit `b95464c`, `f1a02e5`, `7a57bfb`, `cd84f4f` là của Lab Coach (`HungBil`) trong repo gốc, không tính vào đóng góp của nhóm.

⬜ **Lưu ý cần xử lý trước khi nộp**: commit `caa0fd2` (`submission/evidence/cp1.png`) hiện chỉ nằm trên nhánh `origin/feature/thieu`, chưa được merge vào nhánh nộp — merge vào rồi mới push, nếu không ảnh evidence checkpoint 1 sẽ không có trong bài.

## 8. Checklist ảnh chụp còn thiếu

Toàn bộ số liệu và evidence dạng text/HTML đã đủ. Chỉ còn bốn ảnh phải chụp tay, lưu vào `submission/evidence/` đúng tên dưới đây:

| File cần chụp | Chụp ở đâu | Phục vụ mục nào |
|---|---|---|
| `trace-waterfall.png` | Langfuse → mở trace `f5c38deff56a53029bbf4dea5c6eaa49`, để thấy span retrieval ~2,5s | Mục 3, yêu cầu "một trace waterfall" |
| `prompt-versions.png` | Langfuse → Prompts → `day13-chat`, thấy v1 và v2 cùng label | Mục 4 |
| `prompt-label-rollback.png` | Langfuse → `day13-chat`, trạng thái label sau rollback (`v1 = baseline, production`) | Mục 4 |
| `dashboard.png` / `dashboard-baseline.png` | Mở `evidence/dashboard.html` và `evidence/dashboard-baseline.html` bằng trình duyệt rồi chụp | Mục 5 |

Đã có sẵn: `health.png` (checkpoint 0). Còn `cp1.png` nằm ở nhánh `feature/thieu` — xem lưu ý ở mục 7.

## Phụ lục — cách chạy lại toàn bộ

```bash
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file .env      # terminal 1

python scripts/prompt_ops.py setup                  # tạo prompt v1/v2
python scripts/load_test.py                         # baseline
python scripts/validate_logs.py                     # 100/100
python scripts/validate_dashboard.py                # 6/6 panel
python scripts/render_dashboard.py                  # dựng dashboard HTML
python scripts/inject_incident.py                   # bật incident chính thức
python scripts/load_test.py --challenge --concurrency 5
python scripts/inject_incident.py --disable
python scripts/trace_evidence.py --since-minutes 10 # evidence trace
python -m pytest -q                                 # 22 passed
```

Script của nhóm (không có sẵn trong repo gốc): `scripts/render_dashboard.py`, `scripts/prompt_ops.py`, `scripts/trace_evidence.py`.

**Kiểm tra secret và PII trong Git** (đã chạy trên toàn bộ file được Git theo dõi):

- `.env` không được commit — `.gitignore` chặn `.env`, `.venv/`, `data/logs.jsonl`, `data/audit.jsonl`; chỉ `.env.example` nằm trong repo và không chứa key thật.
- `git grep` tìm `sk-lf-` / `pk-lf-` chỉ khớp phần placeholder trong `SETUP.md` (`pk-lf-...`, `sk-lf-...`), không có key thật.
- Quét regex email / số thẻ / số điện thoại trên `submission/evidence/*` không có kết quả thật; log evidence chỉ chứa `user_id_hash` và `message_preview` đã redact.
- `config/challenge.json` giữ nguyên như Lab Coach release.
