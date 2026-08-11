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
| `validate_logs.py` | **100/100** — 153 record, 77 correlation ID, 0 thiếu field, 0 PII leak | `evidence/validate-logs.txt` |
| `validate_dashboard.py` | **HỢP LỆ: 6/6 panel** | `evidence/validate-dashboard.txt` |
| Traces trên Langfuse | **20 trace gần nhất** đều có metadata đầy đủ và `prompt_source=langfuse`; mỗi trace có 3 observation (root generation + span `rag_retrieve` + span `llm_generate`) | `evidence/traces-recent.txt` (20 trace), `evidence/traces-challenge.txt` (6 trace kèm span), `evidence/traces-prompt-versions.txt` (4) |
| PII leak còn lại | **0** | `evidence/validate-logs.txt` |
| Dashboard | `evidence/dashboard.html` (sau sự cố) và `evidence/dashboard-baseline.html` (trước sự cố) | `evidence/dashboard*.html` |
| Public tests | 22 passed | `python -m pytest -q` |

Môi trường: Python 3.11.9, Langfuse Cloud (`https://cloud.langfuse.com`), fake LLM nên không tốn API key trả phí.

**Project Langfuse chứa evidence**: `cmso2fy6e03umad0cv9huvgox`. Toàn bộ trace ID trong báo cáo này chỉ mở được bằng cặp key của project đó — nếu chấm bằng key khác thì mọi link trace sẽ trả về 404. Prompt `day13-chat` (v1, v2) cũng nằm trong project này.

## 3. Logging và tracing

**Correlation ID** — `app/middleware.py` sinh ID dạng `req-<8 hex>` cho mỗi request, hoặc nhận lại `x-request-id` của client nếu ID đó khớp `^[A-Za-z0-9._-]{1,64}$` (ID từ client là dữ liệu không tin cậy, không cho ký tự lạ chui vào log). ID được `bind_contextvars` nên mọi log trong request tự mang theo, và trả về client qua header `x-request-id` + `x-response-time-ms`. Đầu mỗi request gọi `clear_contextvars()` để context không rò rỉ sang request khác.

- Evidence correlation ID: `evidence/logs-challenge.jsonl` — mỗi cặp `request_received`/`response_sent` dùng chung một `correlation_id`, ví dụ `req-76c95062`.

**Metadata** — `app/main.py` bind `user_id_hash`, `session_id`, `feature`, `model`, `env` cho toàn bộ log của request. `user_id` không bao giờ được ghi nguyên văn, chỉ ghi SHA-256 cắt 12 ký tự (`hash_user_id`).

**PII redaction** — `scrub_event` được đăng ký trong pipeline `structlog` **trước** processor ghi file, nên dữ liệu chưa che không bao giờ chạm đĩa. Pattern trong `app/pii.py`: email, thẻ tín dụng, số điện thoại VN (5 định dạng), CCCD 12 số, hộ chiếu VN, địa chỉ VN theo số nhà + từ khoá hành chính.

- Evidence PII redaction: log của `u01` (input có `student@vinuni.edu.vn`) ghi `message_preview` thành `[REDACTED_EMAIL]`; `u05` (`0987654321`) và `u09` (thẻ `4111 1111 1111 1111`) tương tự. `validate_logs.py` quét PII bằng regex độc lập với code redaction và báo 0 leak.
- PII trong trace: cả `rag_retrieve` và `llm_generate` đều đặt `capture_input=False, capture_output=False`. Nếu để mặc định, Langfuse sẽ lưu nguyên câu hỏi thô của người dùng — log đã che rồi mà trace vẫn giữ bản chưa che thì coi như chưa che.

**Cấu trúc span** — mỗi request tạo 3 observation:

| Observation | Loại | Nguồn |
|---|---|---|
| root (generation) | `GENERATION` | `LabAgent.run` — `app/agent.py` |
| `rag_retrieve` | `SPAN` (retriever) | `mock_rag.retrieve` — bước tìm tài liệu |
| `llm_generate` | `SPAN` | `FakeLLM.generate` — bước sinh câu trả lời |

Tách được ba span này là điều kiện để bước "khoanh vùng span bất thường" ở mục 6 có ý nghĩa: nếu chỉ instrument mỗi `run`, waterfall chỉ còn một thanh duy nhất và không chỉ ra được bước nào chậm.

**Một span đáng chú ý** — trace `da51a9ee148b5663e783422d75543cbb` (session `k3-challenge-s03`) báo `latency=2.656s`, tách ra thành `rag_retrieve` **2.503s** và `llm_generate` **0.151s** — retrieval chiếm 94% thời gian. Nhưng client gửi request này phải chờ **13.30s**. Khoảng chênh 10.6s không nằm trong bất kỳ span nào — đó chính là manh mối của phần 6.

- Evidence trace waterfall: ⬜ ảnh chụp trace `da51a9ee148b5663e783422d75543cbb` trên Langfuse (URL ở mục 8); bản text đầy đủ ở `evidence/traces-challenge.txt`.

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

Cả bốn trace đều có `prompt_source=langfuse` — tức app thật sự lấy prompt managed chứ không rơi về template local. (Đã kiểm tra lại bằng API: cả bốn trace ID này vẫn tồn tại trong project `cmso2fy6e03umad0cv9huvgox`, và `GET /api/public/v2/prompts` trả về `day13-chat` với `versions: [1, 2]`.)

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

| Panel | Trước sự cố | Sau sự cố | Threshold | Trạng thái |
|---|---|---|---|---|
| latency | p95 = 153 ms | **p95 = 2.652 ms** | p95 ≤ 3.000 ms | đạt (sát ngưỡng) |
| traffic | 35,00 req/phút | 37,50 req/phút | rate ≥ 1/phút | đạt |
| errors | 0,00% | 0,00% | ≤ 2% | đạt |
| cost | $0,1458 | $0,1565 | tổng ≤ $2,5 | đạt |
| tokens | 9.261 | 9.940 | mỗi field ≤ 50.000 | đạt |
| quality | 0,880 | 0,879 | mean ≥ 0,75 | đạt |

Cột "trước sự cố" dựng từ log đã lọc bỏ các session `k3-challenge-*`; cột "sau sự cố" là toàn bộ log trong cùng cửa sổ 60 phút. Chỉ đúng một panel đổi trạng thái đáng kể — latency — còn năm panel kia gần như đứng yên; đó là lý do phần điều tra ở mục 6 chỉ đi theo hướng latency.

- Evidence dashboard: `evidence/dashboard.html` (sau) và `evidence/dashboard-baseline.html` (trước). ⬜ Chụp màn hình cả hai (đã hiện sẵn tên panel, time range 60 phút, refresh 30s, đơn vị và threshold).

**SLO đã chọn và lý do** (`config/slo.yaml`) — bốn SLI bám đúng bốn nhóm rủi ro khác nhau: latency p95 ≤ 3000ms (trải nghiệm chờ), error rate ≤ 2% (lỗi thấy được), cost ≤ $2,5/ngày (ngân sách), quality mean ≥ 0,75 (lỗi âm thầm mà hai chỉ số đầu không bắt được). Baseline đo được p95 = 153 ms nên ngưỡng 3.000 ms còn rất nhiều dư địa; đây là lựa chọn có chủ ý để alert chỉ kêu khi thực sự bất thường. Mặt trái của biên rộng đó lộ ra ngay trong challenge: sự cố đẩy p95 lên 2.652 ms, gấp 17 lần baseline mà vẫn không chạm ngưỡng — xem mục 6.

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

| Chỉ số | Baseline (70 request) | Trong sự cố (+5 request challenge) |
|---|---|---|
| latency_p50 | 152 ms | 152 ms |
| **latency_p95** | **153 ms** | **2.652 ms** (+2.499 ms) |
| latency_p99 | 1.196 ms | 2.654 ms |
| traffic | 70 | 75 |
| error_breakdown | {} | {} |
| quality_avg | 0,880 | 0,879 |

p50 gần như không đổi còn p95 tăng gấp đôi — dấu hiệu kinh điển của chậm ở phần đuôi, chỉ một nhóm request bị ảnh hưởng chứ không phải cả hệ thống. Không có lỗi nào (`error_breakdown` rỗng ở cả hai lần đo) và quality gần như không đổi (0,88 → 0,873), nên đây là sự cố latency thuần tuý chứ không phải lỗi chất lượng hay lỗi tool. Nhóm request bị ảnh hưởng chính là feature `refund` — đúng `affected_feature` mà challenge khai báo.

p95 = 2.651 ms đã vượt `latency_threshold_ms = 2000` của challenge, nhưng **vẫn dưới SLO 3.000 ms của nhóm** — chi tiết này quay lại ở phần root cause.

**Nhưng client lại đo được 10,7s đến 13,3s** cho chính năm request đó (output `load_test.py`: 10.661 / 13.323 / 13.322 / 13.321 / 13.322 ms). Chênh lệch giữa 2,65s mà server báo và 13,3s mà người dùng chịu chính là phần đáng điều tra nhất.

### Trace: khoanh vùng span bất thường

Năm trace của challenge (`evidence/traces-challenge.txt`), nối với log qua `session_id`:

| Session | Trace ID | Tổng trace | span `rag_retrieve` | span `llm_generate` |
|---|---|---|---|---|
| k3-challenge-s01 | `0afa191ed8469d7a6783ac272f8d7f3b` | 2,653s | **2,502s** | 0,151s |
| k3-challenge-s02 | `cb6d899654f126d01e909e32c36b2f04` | 2,655s | **2,502s** | 0,152s |
| k3-challenge-s03 | `da51a9ee148b5663e783422d75543cbb` | 2,656s | **2,503s** | 0,151s |
| k3-challenge-s04 | `e7f5ab37365da4f249972cea4cded6c7` | 2,652s | **2,500s** | 0,152s |
| k3-challenge-s05 | `17bcce72457d190b03321160264a5ceb` | 2,655s | **2,501s** | 0,151s |
| (đối chứng) s10, feature `qa` | `5446e73823aa8278742c87d1685f16f4` | 0,154s | 0,000s | 0,153s |

Đây chính là bước khoanh vùng: span `rag_retrieve` chiếm **94%** thời gian của trace, còn `llm_generate` giữ nguyên 0,15s như lúc khỏe mạnh. Trace đối chứng ở dòng cuối (chạy khi incident đã tắt) cho thấy `rag_retrieve` bình thường tốn 0,000s — vậy toàn bộ 2,5s là do bước retrieval, không phải do LLM, không phải do prompt.

Nhưng trace **không** giải thích được vì sao request cuối phải chờ 13,3s: cả năm trace đều chỉ dài 2,65s. Phần chờ còn lại xảy ra **trước khi** trace được tạo, nên không span nào nhìn thấy — phải sang log.

### Log: chứng minh root cause

`evidence/challenge-timeline.txt`, dựng từ `evidence/logs-challenge.jsonl`:

```
correlation_id  session                 nhận (t+s)   trả (t+s)  latency_ms log  client chờ (s)
req-a8276c71    k3-challenge-s01              0.00        2.66            2652            2.66
req-8721beaf    k3-challenge-s02              2.66        5.32            2653            5.32
req-d79c1273    k3-challenge-s04              5.32        7.98            2653            7.98
req-bb580fc8    k3-challenge-s05              7.98       10.64            2654           10.64
req-9cff6691    k3-challenge-s03             10.65       13.30            2652           13.30
```

Năm request được client gửi song song, nhưng log `request_received` của mỗi request chỉ được ghi **đúng vào lúc** request trước ghi `response_sent`. Chúng bị xử lý tuần tự, mỗi lượt cách nhau đúng 2,65s. Bảng này dựng lại được bằng `python scripts/challenge_timeline.py`.

### Root cause

Hai nguyên nhân chồng lên nhau:

1. **Nguyên nhân trực tiếp** — incident `rag_slow` thêm `time.sleep(2.5)` vào `mock_rag.retrieve()`, làm mỗi request chậm thêm 2,5s.
2. **Nguyên nhân khuếch đại (lỗi kiến trúc)** — `app/main.py` khai báo endpoint `async def chat`, nhưng bên trong gọi thẳng `agent.run()` là hàm **đồng bộ**. Một lệnh `time.sleep()` đồng bộ trong endpoint `async` sẽ chặn cả event loop, nên toàn bộ request khác phải xếp hàng. Đây là head-of-line blocking: sự cố 2,5s bị nhân lên thành 13,3s ở concurrency 5, và sẽ tệ tuyến tính theo số request đồng thời.

Bằng chứng cho điểm 2 nằm ở cột "nhận (t+s)": nếu app xử lý song song đúng nghĩa, cả năm `request_received` phải được ghi gần như cùng lúc và cả năm request cùng xong sau ~2,65s. Việc chúng cách nhau đều đặn 2,65s chỉ có thể xảy ra khi event loop bị chặn.

**Điểm mù quan sát đi kèm** — `latency_ms` được đo bên trong `LabAgent.run`, tức chỉ tính từ lúc request giành được event loop. Nó bỏ qua toàn bộ thời gian xếp hàng. Hệ quả trực tiếp: dashboard báo p95 = 2.652 ms, **vẫn dưới SLO 3.000 ms**, nên `chat_latency_p95_slo_breach` sẽ **không kêu** trong khi người dùng đang chờ 13,3 giây — sai số gấp 5 lần. Sự cố này lẽ ra lọt lưới hoàn toàn.

**Điểm mù thứ hai — trace không có span con.** Ở lần chạy đầu, `retrieve` và `generate` chưa được instrument riêng nên mỗi trace chỉ có đúng một observation: waterfall là một thanh 2,65s duy nhất, không chỉ ra được bước nào chậm. Bước "dùng trace để khoanh vùng span bất thường" khi đó không thực hiện được — chỉ có thể đoán từ code. Nhóm đã thêm span `rag_retrieve` và `llm_generate` rồi chạy lại challenge; số liệu ở mục này là của lần chạy sau. Bài học: **một trace không có span con thì không phải công cụ chẩn đoán, nó chỉ là một cái đồng hồ bấm giờ.**

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
6. **Bắt buộc mỗi dependency ngoài phải có span riêng.** Đã làm cho `rag_retrieve` và `llm_generate`; quy ước: thêm một lệnh gọi ra ngoài (vector store, LLM, HTTP) thì phải kèm `@observe`, nếu không sự cố sau lại rơi vào đúng điểm mù thứ hai ở trên.

## 7. Đóng góp cá nhân

Bảng dưới được dựng từ `git log --all`; tài khoản Git được map sang tên thật như sau — **mỗi thành viên kiểm tra lại dòng của mình trước khi nộp**, cột "Điều đã học" phải tự viết.

| Thành viên | Tài khoản Git | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|---|
| Nguyễn Hoàng Minh (QA) | `Hoàng Minh` / minhworkplace@gmail.com | Setup baseline và evidence checkpoint 0 (`health.png`); chạy validator; thêm span `rag_retrieve`/`llm_generate` và tắt capture input để trace không giữ PII; chạy lại toàn bộ challenge lấy evidence có span; `scripts/challenge_timeline.py`; tổng hợp và viết `submission/REPORT.md`; merge nhánh của các thành viên | `39d6a99` (CP0), `709ff3d` + `318ba6f` (merge), `61cea5a`, `91cfc5f` + commit cuối (report và span) | ⬜ |
| Nguyễn Gia Thiều (Backend Engineer) | `thieunguyen879` | Checkpoint 1: logging JSON, correlation ID middleware, enrichment metadata, PII redaction; instrument trace trong `app/agent.py`; incident hook `mock_rag` | `bf5c68a` (cp1), `caa0fd2` (evidence cp1.png), `f60d13c` (merge) | ⬜ |
| Nguyễn Quốc Thịnh (SRE & Alerts Engineer) | `ngthomas562-hub` | Checkpoint 2 và 3: `scripts/render_dashboard.py`, `scripts/prompt_ops.py`, `scripts/trace_evidence.py`; `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`; thu thập toàn bộ evidence challenge | `307ebd9` | ⬜ |

Các commit `b95464c`, `f1a02e5`, `7a57bfb`, `cd84f4f` là của Lab Coach (`HungBil`) trong repo gốc, không tính vào đóng góp của nhóm.

Nhánh `feature/thieu` đã được merge vào nhánh nộp (`318ba6f`), nên `evidence/cp1.png` có mặt trong bài.

## 8. Checklist ảnh chụp còn thiếu

Toàn bộ số liệu và evidence dạng text/HTML đã đủ. Chỉ còn bốn ảnh phải chụp tay, lưu vào `submission/evidence/` đúng tên dưới đây:

| File cần chụp | Chụp ở đâu | Phục vụ mục nào |
|---|---|---|
| `trace-waterfall.png` | URL bên dưới — waterfall phải thấy rõ `rag_retrieve` 2,50s nằm cạnh `llm_generate` 0,15s | Mục 3, yêu cầu "một trace waterfall" |
| `prompt-versions.png` | Langfuse → Prompts → `day13-chat`, thấy v1 và v2 cùng label | Mục 4 |
| `prompt-label-rollback.png` | Langfuse → `day13-chat`, trạng thái label sau rollback (`v1 = baseline, production`) | Mục 4 |
| `dashboard.png` / `dashboard-baseline.png` | Mở `evidence/dashboard.html` và `evidence/dashboard-baseline.html` bằng trình duyệt rồi chụp | Mục 5 |

URL trace waterfall (đăng nhập Langfuse bằng tài khoản sở hữu project `cmso2fy6e03umad0cv9huvgox`):

```
https://cloud.langfuse.com/project/cmso2fy6e03umad0cv9huvgox/traces/da51a9ee148b5663e783422d75543cbb
```

Đã có sẵn: `health.png` (checkpoint 0) và `cp1.png` (checkpoint 1).

## Phụ lục — cách chạy lại toàn bộ

```bash
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file .env      # terminal 1

python scripts/prompt_ops.py setup                  # tạo prompt v1/v2
python scripts/load_test.py                         # baseline (chạy 7 vòng để panel traffic đủ dữ liệu)
python scripts/validate_logs.py                     # 100/100
python scripts/validate_dashboard.py                # 6/6 panel
python scripts/render_dashboard.py --out submission/evidence/dashboard.html
python scripts/inject_incident.py                   # bật incident chính thức
python scripts/load_test.py --challenge --concurrency 5
python scripts/inject_incident.py --disable
python scripts/challenge_timeline.py                # logs-challenge.jsonl + timeline
python scripts/trace_evidence.py --since-minutes 4 --limit 6 --spans \
       --out submission/evidence/traces-challenge.txt
python -m pytest -q                                 # 22 passed
```

Hai lưu ý khi chạy lại:

- `data/logs.jsonl` tích luỹ qua nhiều lần chạy. Nếu file còn log của lần chạy **trước khi** có code enrichment thì `validate_logs.py` sẽ trừ điểm cho chính những record cũ đó (nhóm gặp đúng lỗi này: 50/100 với 20 record cũ). Đổi tên file cũ đi rồi chạy lại là sạch.
- `load_test.py` và `inject_incident.py` nhận biến môi trường `LAB_BASE_URL` (mặc định `http://127.0.0.1:8000`) để chạy được khi cổng 8000 đang bận.

Script của nhóm (không có sẵn trong repo gốc): `scripts/render_dashboard.py`, `scripts/prompt_ops.py`, `scripts/trace_evidence.py`, `scripts/challenge_timeline.py`.

**Kiểm tra secret và PII trong Git** (đã chạy trên toàn bộ file được Git theo dõi):

- `.env` không được commit — `.gitignore` chặn `.env`, `.venv/`, `data/logs.jsonl`, `data/audit.jsonl`; chỉ `.env.example` nằm trong repo và không chứa key thật.
- `git grep` tìm `sk-lf-` / `pk-lf-` chỉ khớp phần placeholder trong `SETUP.md` (`pk-lf-...`, `sk-lf-...`), không có key thật.
- Quét regex email / số thẻ / số điện thoại trên `submission/evidence/*` không có kết quả thật; log evidence chỉ chứa `user_id_hash` và `message_preview` đã redact.
- `config/challenge.json` giữ nguyên như Lab Coach release.
