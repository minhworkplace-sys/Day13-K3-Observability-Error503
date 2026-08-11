"""Dựng dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

Contract quyết định event, field, phép tổng hợp, đơn vị và threshold; script này chỉ
đọc contract rồi vẽ đúng những gì contract nói. Không hard-code giá trị panel nào.

    python scripts/render_dashboard.py
    python scripts/render_dashboard.py --out submission/evidence/dashboard-incident.html
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile
from scripts.validate_dashboard import load_dashboard_config

# Palette tham chiếu đã chạy qua validate_palette.js (light + dark, --pairs all).
SERIES = ("var(--series-1)", "var(--series-2)", "var(--series-3)")

CHART_W = 560
CHART_H = 190
PAD_L, PAD_R, PAD_T, PAD_B = 52, 14, 14, 28


# --------------------------------------------------------------------------- data


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def read_records(log_path: Path, window_minutes: int) -> tuple[list[dict], datetime, datetime]:
    if not log_path.exists():
        raise SystemExit(f"Không tìm thấy {log_path}. Chạy API và scripts/load_test.py trước.")

    records: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_ts(record.get("ts", ""))
        if ts is None:
            continue
        record["_ts"] = ts
        records.append(record)

    if not records:
        raise SystemExit(f"{log_path} không có log JSON hợp lệ nào.")

    # Cửa sổ neo vào log mới nhất, để ảnh evidence vẫn đúng khi xem lại sau buổi lab.
    end = max(record["_ts"] for record in records)
    start = end - timedelta(minutes=window_minutes)
    inside = [record for record in records if start < record["_ts"] <= end]
    return inside, start, end


def minute_key(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def minute_axis(records: list[dict]) -> list[datetime]:
    if not records:
        return []
    first = minute_key(min(record["_ts"] for record in records))
    last = minute_key(max(record["_ts"] for record in records))
    span = int((last - first).total_seconds() // 60)
    return [first + timedelta(minutes=i) for i in range(span + 1)]


def bucket(records: list[dict], event: str, field: str | None = None) -> dict[datetime, list]:
    out: dict[datetime, list] = defaultdict(list)
    for record in records:
        if record.get("event") != event:
            continue
        if field is None:
            out[minute_key(record["_ts"])].append(1)
        elif isinstance(record.get(field), (int, float)):
            out[minute_key(record["_ts"])].append(record[field])
    return out


def values_of(records: list[dict], event: str, field: str) -> list:
    return [
        record[field]
        for record in records
        if record.get("event") == event and isinstance(record.get(field), (int, float))
    ]


# ------------------------------------------------------------------------ drawing


def fmt(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:,.4f}"
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "score_0_to_1":
        return f"{value:.3f}"
    if unit == "ms":
        return f"{value:,.0f} ms"
    if unit == "tokens":
        return f"{value:,.0f}"
    if unit == "requests_per_minute":
        return f"{value:,.2f}/min"
    return f"{value:,.2f}"


def nice_ceiling(value: float) -> float:
    """Làm tròn lên tới bội số "đẹp" gần nhất; hoạt động cả với giá trị < 1 như cost_usd."""
    if value <= 0:
        return 1.0
    step = 10 ** math.floor(math.log10(value))
    return math.ceil(value / step) * step


class Chart:
    """SVG builder dùng chung cho line và column; toạ độ y luôn bắt đầu từ 0."""

    def __init__(self, axis: list, y_max: float, unit: str, categorical: bool = False) -> None:
        self.axis = axis
        self.y_max = y_max or 1.0
        self.unit = unit
        # categorical=True: trục ngang là danh mục (ví dụ error_type), nhãn hiện đủ.
        self.categorical = categorical
        self.parts: list[str] = []

    def label_at(self, index: int) -> str:
        item = self.axis[index]
        return item.strftime("%H:%M") if isinstance(item, datetime) else str(item)

    def x(self, index: int) -> float:
        usable = CHART_W - PAD_L - PAD_R
        if len(self.axis) <= 1:
            return PAD_L + usable / 2
        return PAD_L + usable * index / (len(self.axis) - 1)

    def band(self) -> float:
        usable = CHART_W - PAD_L - PAD_R
        return usable / max(1, len(self.axis))

    def y(self, value: float) -> float:
        usable = CHART_H - PAD_T - PAD_B
        return CHART_H - PAD_B - usable * (value / self.y_max)

    def grid(self) -> None:
        for i in range(5):
            value = self.y_max * i / 4
            y = self.y(value)
            self.parts.append(
                f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}"/>'
            )
            self.parts.append(
                f'<text class="tick" x="{PAD_L - 8}" y="{y + 3.5:.1f}" text-anchor="end">'
                f"{self._tick(value)}</text>"
            )
        base = self.y(0)
        self.parts.append(
            f'<line class="axis" x1="{PAD_L}" y1="{base:.1f}" x2="{CHART_W - PAD_R}" y2="{base:.1f}"/>'
        )
        if self.categorical:
            positions = list(range(len(self.axis)))
        else:
            # Chuỗi thời gian chỉ cần nhãn đầu và cuối; các mốc giữa nằm trong tooltip/bảng.
            positions = sorted({0, len(self.axis) - 1})
        for index in positions:
            if index < 0:
                continue
            if self.categorical:
                anchor = "middle"
            else:
                anchor = "start" if index == 0 else "end"
            self.parts.append(
                f'<text class="tick" x="{self.x(index):.1f}" y="{CHART_H - 8}" text-anchor="{anchor}">'
                f"{html.escape(self.label_at(index))}</text>"
            )

    def _tick(self, value: float) -> str:
        if self.unit == "usd":
            decimals = max(3, 2 - math.floor(math.log10(self.y_max)))
            return f"{value:.{decimals}f}"
        if self.unit == "score_0_to_1":
            return f"{value:.2f}"
        if value >= 1000:
            return f"{value / 1000:.0f}k"
        return f"{value:.0f}" if value == int(value) else f"{value:.1f}"

    def threshold(self, value: float, label: str) -> None:
        if value > self.y_max:
            return
        y = self.y(value)
        self.parts.append(
            f'<line class="slo" x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}"/>'
        )
        self.parts.append(
            f'<text class="slo-label" x="{CHART_W - PAD_R}" y="{y - 6:.1f}" text-anchor="end">'
            f"{html.escape(label)}</text>"
        )

    def line(self, points: list[float | None], color: str, name: str) -> None:
        drawn = [(self.x(i), self.y(v), v) for i, v in enumerate(points) if v is not None]
        if not drawn:
            return
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y, _) in enumerate(drawn)
        )
        self.parts.append(f'<path class="line" d="{path}" stroke="{color}"/>')
        for i, value in enumerate(points):
            if value is None:
                continue
            tip = f"{self.label_at(i)} · {name}: {fmt(value, self.unit)}"
            self.parts.append(
                f'<circle class="dot" cx="{self.x(i):.1f}" cy="{self.y(value):.1f}" r="4" '
                f'fill="{color}" data-tip="{html.escape(tip)}"/>'
            )
        last_x, last_y, last_v = drawn[-1]
        self.parts.append(
            f'<text class="end-label" x="{last_x - 8:.1f}" y="{last_y - 10:.1f}" text-anchor="end">'
            f"{html.escape(fmt(last_v, self.unit))}</text>"
        )

    def columns(self, groups: list[list[float]], colors: list[str], names: list[str]) -> None:
        series_count = max(1, len(colors))
        # 2px surface gap giữa các cột kề nhau; bề rộng cột cap ở 24px.
        slot = max(4.0, self.band() - 4)
        width = min(24.0, (slot - 2 * (series_count - 1)) / series_count)
        base = self.y(0)
        for i, values in enumerate(groups):
            center = self.x(i) if len(self.axis) > 1 else PAD_L + (CHART_W - PAD_L - PAD_R) / 2
            block = width * series_count + 2 * (series_count - 1)
            left = center - block / 2
            for s, value in enumerate(values):
                if value is None or value <= 0:
                    continue
                x = left + s * (width + 2)
                y = self.y(value)
                tip = f"{self.label_at(i)} · {names[s]}: {fmt(value, self.unit)}"
                self.parts.append(
                    f'<path class="col" d="{rounded_column(x, y, width, base - y)}" '
                    f'fill="{colors[s]}" data-tip="{html.escape(tip)}"/>'
                )

    def render(self) -> str:
        return (
            f'<svg viewBox="0 0 {CHART_W} {CHART_H}" role="img" preserveAspectRatio="xMidYMid meet">'
            + "".join(self.parts)
            + "</svg>"
        )


def rounded_column(x: float, y: float, w: float, h: float) -> str:
    """Cột bo 4px ở đầu dữ liệu, vuông ở baseline."""
    r = min(4.0, w / 2, max(0.0, h))
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h:.1f} Z"
    )


# ------------------------------------------------------------------------- panels


class Panel:
    def __init__(self, spec: dict) -> None:
        self.id = spec["id"]
        self.title = spec["title"]
        self.unit = spec["unit"]
        self.query = spec["query"]
        self.threshold = spec["threshold"]
        self.stats: list[tuple[str, str]] = []
        self.chart_html = ""
        self.legend: list[tuple[str, str]] = []
        self.table: list[tuple[str, str]] = []
        self.observed: float | None = None
        self.note = ""

    @property
    def ok(self) -> bool | None:
        if self.observed is None:
            return None
        if self.threshold["operator"] == "lte":
            return self.observed <= self.threshold["value"]
        return self.observed >= self.threshold["value"]

    @property
    def threshold_label(self) -> str:
        op = "≤" if self.threshold["operator"] == "lte" else "≥"
        return f'{self.threshold["aggregation"]} {op} {fmt(self.threshold["value"], self.unit)}'


def build_panels(spec_panels: list[dict], records: list[dict], axis: list[datetime]) -> list[Panel]:
    by_id = {spec["id"]: spec for spec in spec_panels}
    panels: list[Panel] = []
    minutes = max(1, len(axis))

    # --- latency: p50/p95/p99 của response_sent.latency_ms
    panel = Panel(by_id["latency"])
    latencies = values_of(records, "response_sent", "latency_ms")
    buckets = bucket(records, "response_sent", "latency_ms")
    if latencies:
        for label, p in (("p50", 50), ("p95", 95), ("p99", 99)):
            panel.stats.append((label, fmt(percentile(latencies, p), panel.unit)))
        panel.observed = percentile(latencies, 95)
        y_max = nice_ceiling(max(max(latencies), panel.threshold["value"]) * 1.15)
        chart = Chart(axis, y_max, panel.unit)
        chart.grid()
        chart.threshold(panel.threshold["value"], f'SLO {panel.threshold_label}')
        for idx, (label, p) in enumerate((("p50", 50), ("p95", 95), ("p99", 99))):
            series = [
                percentile(buckets[m], p) if buckets.get(m) else None for m in axis
            ]
            chart.line(series, SERIES[idx], label)
            panel.legend.append((label, SERIES[idx]))
        panel.chart_html = chart.render()
        panel.table = [
            (m.strftime("%H:%M"), fmt(percentile(buckets[m], 95), panel.unit))
            for m in axis
            if buckets.get(m)
        ]
    panels.append(panel)

    # --- traffic: count(request_received) theo phút
    panel = Panel(by_id["traffic"])
    buckets = bucket(records, "request_received")
    total = sum(len(v) for v in buckets.values())
    if total:
        rate = total / minutes
        panel.observed = rate
        panel.stats = [("count", f"{total:,}"), ("rate_per_minute", fmt(rate, panel.unit))]
        y_max = nice_ceiling(max(len(v) for v in buckets.values()) * 1.2)
        chart = Chart(axis, y_max, "requests")
        chart.grid()
        chart.columns([[len(buckets.get(m, []))] for m in axis], [SERIES[0]], ["requests"])
        panel.chart_html = chart.render()
        panel.table = [
            (m.strftime("%H:%M"), f"{len(buckets.get(m, [])):,}") for m in axis if buckets.get(m)
        ]
    panels.append(panel)

    # --- errors: error_rate_pct theo thời gian + count_by_value theo error_type
    panel = Panel(by_id["errors"])
    received_buckets = bucket(records, "request_received")
    failed_buckets = bucket(records, "request_failed")
    received = sum(len(v) for v in received_buckets.values())
    failed = [r for r in records if r.get("event") == "request_failed"]
    rate = (len(failed) / received * 100) if received else 0.0
    panel.observed = rate
    panel.stats = [("error_rate_pct", fmt(rate, panel.unit)), ("failed", f"{len(failed):,}")]

    # Luôn vẽ error rate theo phút, kể cả khi bằng 0 — panel phẳng ở 0% cũng là thông tin.
    per_minute = [
        (len(failed_buckets.get(m, [])) / len(received_buckets[m]) * 100)
        if received_buckets.get(m)
        else None
        for m in axis
    ]
    y_max = max(nice_ceiling(panel.threshold["value"] * 2), nice_ceiling(max([v for v in per_minute if v is not None] or [0]) * 1.25))
    chart = Chart(axis, y_max, panel.unit)
    chart.grid()
    chart.threshold(panel.threshold["value"], f"SLO {panel.threshold_label}")
    chart.line(per_minute, SERIES[1], "error_rate")
    panel.chart_html = chart.render()

    breakdown = Counter(r.get("error_type", "unknown") for r in failed)
    if breakdown:
        panel.table = [(k, f"{v:,}") for k, v in breakdown.most_common()]
        panel.note = "count_by_value: " + ", ".join(f"{k}={v}" for k, v in breakdown.most_common())
    else:
        panel.table = [
            (m.strftime("%H:%M"), fmt(v, panel.unit)) for m, v in zip(axis, per_minute) if v is not None
        ]
        panel.note = "Không có request_failed trong cửa sổ nên count_by_value rỗng."
    panels.append(panel)

    # --- cost: sum(cost_usd) theo phút + tổng
    panel = Panel(by_id["cost"])
    buckets = bucket(records, "response_sent", "cost_usd")
    costs = values_of(records, "response_sent", "cost_usd")
    if costs:
        total_cost = sum(costs)
        panel.observed = total_cost
        panel.stats = [
            ("total", fmt(total_cost, panel.unit)),
            ("avg/request", fmt(mean(costs), panel.unit)),
        ]
        per_minute = [sum(buckets.get(m, [])) for m in axis]
        chart = Chart(axis, nice_ceiling(max(per_minute) * 1.25), panel.unit)
        chart.grid()
        chart.columns([[v] for v in per_minute], [SERIES[0]], ["cost"])
        panel.chart_html = chart.render()
        panel.table = [
            (m.strftime("%H:%M"), fmt(v, panel.unit)) for m, v in zip(axis, per_minute) if v
        ]
        panel.note = f'Threshold {panel.threshold_label} áp cho tổng cả cửa sổ.'
    panels.append(panel)

    # --- tokens: sum(tokens_in), sum(tokens_out)
    panel = Panel(by_id["tokens"])
    tin = bucket(records, "response_sent", "tokens_in")
    tout = bucket(records, "response_sent", "tokens_out")
    sum_in = sum(values_of(records, "response_sent", "tokens_in"))
    sum_out = sum(values_of(records, "response_sent", "tokens_out"))
    if sum_in or sum_out:
        panel.observed = float(max(sum_in, sum_out))
        panel.stats = [("sum(tokens_in)", f"{sum_in:,}"), ("sum(tokens_out)", f"{sum_out:,}")]
        groups = [[sum(tin.get(m, [])), sum(tout.get(m, []))] for m in axis]
        y_max = nice_ceiling(max((max(g) for g in groups), default=1) * 1.2)
        chart = Chart(axis, y_max, panel.unit)
        chart.grid()
        chart.columns(groups, [SERIES[0], SERIES[1]], ["tokens_in", "tokens_out"])
        panel.chart_html = chart.render()
        panel.legend = [("tokens_in", SERIES[0]), ("tokens_out", SERIES[1])]
        panel.table = [
            (m.strftime("%H:%M"), f"{g[0]:,} in / {g[1]:,} out")
            for m, g in zip(axis, groups)
            if g[0] or g[1]
        ]
        panel.note = f'Threshold {panel.threshold_label} áp cho từng field.'
    panels.append(panel)

    # --- quality: mean(quality_score)
    panel = Panel(by_id["quality"])
    scores = values_of(records, "response_sent", "quality_score")
    buckets = bucket(records, "response_sent", "quality_score")
    if scores:
        panel.observed = mean(scores)
        panel.stats = [("mean", fmt(mean(scores), panel.unit)), ("n", f"{len(scores):,}")]
        chart = Chart(axis, 1.0, panel.unit)
        chart.grid()
        chart.threshold(panel.threshold["value"], f"SLO {panel.threshold_label}")
        chart.line(
            [mean(buckets[m]) if buckets.get(m) else None for m in axis], SERIES[2], "mean"
        )
        panel.chart_html = chart.render()
        panel.table = [
            (m.strftime("%H:%M"), fmt(mean(buckets[m]), panel.unit)) for m in axis if buckets.get(m)
        ]
    panels.append(panel)

    return panels


# --------------------------------------------------------------------------- html


STYLE = """
:root{color-scheme:light;--page:#f9f9f7;--surface-1:#fcfcfb;--text-primary:#0b0b0b;
--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,0.10);--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;
--good:#0ca30c;--critical:#d03b3b;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--page:#0d0d0d;--surface-1:#1a1a19;--text-primary:#fff;--text-secondary:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface-1:#1a1a19;
--text-primary:#fff;--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,0.10);--series-1:#3987e5;--series-2:#d95926;
--series-3:#199e70;}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--page);color:var(--text-primary);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{max-width:1200px;margin:0 auto 20px}
h1{font-size:22px;margin:0 0 6px;font-weight:600}
.meta{color:var(--text-secondary);font-size:13px;display:flex;flex-wrap:wrap;gap:6px 18px}
.grid{max-width:1200px;margin:0 auto;display:grid;gap:16px;
grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
padding:16px;overflow:hidden}
.card h2{font-size:15px;margin:0;font-weight:600}
.card-top{display:flex;justify-content:space-between;align-items:start;gap:10px;margin-bottom:2px}
.unit{color:var(--muted);font-size:12px}
.badge{font-size:12px;font-weight:600;white-space:nowrap;padding:2px 8px;border-radius:999px;
border:1px solid var(--border);color:var(--text-secondary)}
.badge.ok{color:var(--good)}.badge.bad{color:var(--critical)}
.stats{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 4px}
.stat-label{color:var(--muted);font-size:12px}
.stat-value{font-size:20px;font-weight:600}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;color:var(--text-secondary);font-size:12px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.key{width:10px;height:10px;border-radius:3px;display:inline-block}
.chart{margin-top:6px;overflow-x:auto}
svg{width:100%;height:auto;display:block;min-width:280px}
.grid-line,.grid{stroke:var(--grid);stroke-width:1}
line.grid{stroke:var(--grid);stroke-width:1}
line.axis{stroke:var(--axis);stroke-width:1}
line.slo{stroke:var(--critical);stroke-width:2}
text{font:11px system-ui,-apple-system,"Segoe UI",sans-serif}
text.tick{fill:var(--muted);font-variant-numeric:tabular-nums}
text.slo-label{fill:var(--critical);font-weight:600}
text.end-label{fill:var(--text-primary);font-weight:600}
path.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
circle.dot{stroke:var(--surface-1);stroke-width:2}
path.col{stroke:none}
.note{color:var(--muted);font-size:12px;margin-top:8px}
details{margin-top:10px}
summary{cursor:pointer;color:var(--text-secondary);font-size:12px}
table{border-collapse:collapse;margin-top:8px;font-size:12px;width:100%}
td,th{text-align:left;padding:3px 10px 3px 0;font-variant-numeric:tabular-nums;
border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:500}
#tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;
background:var(--surface-1);color:var(--text-primary);border:1px solid var(--border);
border-radius:6px;padding:5px 9px;font-size:12px;box-shadow:0 2px 10px rgba(0,0,0,.15);z-index:9}
footer{max-width:1200px;margin:20px auto 0;color:var(--muted);font-size:12px}
"""

SCRIPT = """
const tip=document.getElementById('tip');
document.addEventListener('mouseover',e=>{const t=e.target.closest('[data-tip]');
if(!t)return;tip.textContent=t.getAttribute('data-tip');tip.style.opacity='1';});
document.addEventListener('mousemove',e=>{if(tip.style.opacity!=='1')return;
tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+'px';
tip.style.top=(e.clientY+18)+'px';});
document.addEventListener('mouseout',e=>{if(e.target.closest('[data-tip]'))tip.style.opacity='0';});
"""


def render_html(config: dict, panels: list[Panel], start: datetime, end: datetime, source: Path) -> str:
    dash = config["dashboard"]
    cards = []
    for panel in panels:
        ok = panel.ok
        badge_class = "badge" if ok is None else f"badge {'ok' if ok else 'bad'}"
        badge_text = (
            f"— {panel.threshold_label}"
            if ok is None
            else f"{'✓ đạt' if ok else '▲ vượt'} · {panel.threshold_label}"
        )
        stats = "".join(
            f'<div><div class="stat-label">{html.escape(label)}</div>'
            f'<div class="stat-value">{html.escape(value)}</div></div>'
            for label, value in panel.stats
        ) or '<div class="stat-label">Không có dữ liệu trong cửa sổ</div>'
        legend = (
            '<div class="legend">'
            + "".join(
                f'<span><i class="key" style="background:{color}"></i>{html.escape(name)}</span>'
                for name, color in panel.legend
            )
            + "</div>"
            if panel.legend
            else ""
        )
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in panel.table
        )
        cards.append(
            f'<section class="card"><div class="card-top"><div>'
            f"<h2>{html.escape(panel.title)}</h2>"
            f'<div class="unit">{html.escape(panel.id)} · đơn vị: {html.escape(panel.unit)}</div>'
            f'</div><span class="{badge_class}">{html.escape(badge_text)}</span></div>'
            f'<div class="stats">{stats}</div>{legend}'
            f'<div class="chart">{panel.chart_html}</div>'
            + (f'<p class="note">{html.escape(panel.note)}</p>' if panel.note else "")
            + f"<details><summary>Bảng dữ liệu · {html.escape(panel.query)}</summary>"
            f"<table><thead><tr><th>bucket</th><th>{html.escape(panel.unit)}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details></section>"
        )

    breaches = [p.id for p in panels if p.ok is False]
    summary = (
        f'{len(breaches)} panel vượt threshold: {", ".join(breaches)}'
        if breaches
        else "Tất cả panel trong ngưỡng threshold"
    )
    return (
        "<!doctype html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(dash["title"])}</title><style>{STYLE}</style></head><body>'
        f'<header><h1>{html.escape(dash["title"])}</h1><div class="meta">'
        f'<span>Time range: {dash["time_range_minutes"]} phút</span>'
        f'<span>Refresh: {dash["refresh_seconds"]}s</span>'
        f'<span>Cửa sổ: {start.strftime("%Y-%m-%d %H:%M")}–{end.strftime("%H:%M")} UTC</span>'
        f"<span>Nguồn: {html.escape(str(source))}</span>"
        f"<span>{html.escape(summary)}</span>"
        f'</div></header><div class="grid">{"".join(cards)}</div>'
        f'<footer>Sinh bởi scripts/render_dashboard.py theo contract config/dashboard.yaml '
        f'(schema_version {dash["schema_version"]}). Threshold vẽ bằng đường SLO đỏ trên panel '
        f"latency và quality.</footer>"
        f'<div id="tip"></div><script>{SCRIPT}</script></body></html>'
    )


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ data/logs.jsonl")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "submission" / "evidence" / "dashboard.html"
    )
    args = parser.parse_args()

    config = load_dashboard_config(args.config)
    dash = config["dashboard"]
    records, start, end = read_records(args.logs, dash["time_range_minutes"])
    axis = minute_axis(records)
    panels = build_panels(dash["panels"], records, axis)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(config, panels, start, end, args.logs), encoding="utf-8")

    print(f"Cửa sổ {start:%Y-%m-%d %H:%M}–{end:%H:%M} UTC · {len(records)} log record")
    for panel in panels:
        state = "n/a" if panel.ok is None else ("ĐẠT" if panel.ok else "VƯỢT")
        observed = "-" if panel.observed is None else fmt(panel.observed, panel.unit)
        print(f"  {panel.id:<8} {observed:>16}  threshold {panel.threshold_label:<28} {state}")
    print(f"Dashboard: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
