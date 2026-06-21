#!/usr/bin/env python3
"""Generate static HTML dashboard for NMG Crown Prince Gold Mine — Fuel.

Runs in GitHub Actions daily. Fetches live tank levels + dip history from the
SmartFill / FMT JSON-RPC API, computes daily consumption, an end-of-week
forecast and a month-on-month comparison, then writes docs/index.html which is
served via GitHub Pages and embedded in the Wix site.

Standard library only — no external pip dependencies (mirrors the ERT generator).
"""

import os
import json
import html as _html
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

AWST = ZoneInfo("Australia/Perth")

API_URL       = "https://www.fmtdata.com/API/api.php"
CLIENT_REF    = os.environ.get("SMARTFILL_CLIENT_REF", "")
CLIENT_SECRET = os.environ.get("SMARTFILL_CLIENT_SECRET", "")

_HERE    = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(_HERE, "docs", "index.html")

# NMG brand palette (shared with the ERT dashboard)
NAVY  = "#083045"
GOLD  = "#B19045"
RED   = "#e74c3c"
AMBER = "#f39c12"
GREEN = "#27ae60"

# Daily usage / month-on-month sections are reported for Tank 1 only.
PRIMARY_TANK = "1"


# ── API ───────────────────────────────────────────────────────────────────────

def _call(method, extra_params=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "parameters": {
            "clientReference": CLIENT_REF,
            "clientSecret": CLIENT_SECRET,
            **(extra_params or {}),
        },
        "id": 1,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json-rpc"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    return data["result"]


def get_tank_levels():
    result = _call("Tank:Level", {"columns": [
        "Description", "Volume", "Volume Percent", "Capacity", "Status", "Last Updated"
    ]})
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["values"]]


def get_dips(period):
    result = _call("Tank:Read", {
        "columns": ["Date", "Time", "Tank Number", "Record Type", "Volume"],
        "period": {"type": "recurring", "value": period},
        "order": [{"Date": "ASC"}, {"Time": "ASC"}],
    })
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result.get("data", result.get("values", []))]


# ── Consumption ───────────────────────────────────────────────────────────────

def calc_daily_consumption(dips):
    """Returns {tank_num: {date: consumed_litres}} from raw dip rows.

    For each tank/day, consumption = first reading - last reading. Negative
    values (a delivery / refill) are clamped to 0.
    """
    by_tank_date = defaultdict(lambda: defaultdict(list))
    for row in dips:
        if row.get("Record Type", "").strip().lower() != "dip":
            continue
        try:
            dt = datetime.strptime(row["Date"] + " " + row["Time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError):
            continue
        by_tank_date[str(row["Tank Number"])][dt.date()].append((dt, float(row["Volume"])))

    result = defaultdict(dict)
    for tank_num, dates in by_tank_date.items():
        for date, readings in dates.items():
            readings.sort()
            result[tank_num][date] = max(readings[0][1] - readings[-1][1], 0)
    return result


def short_name(description):
    """'Fuelfix 11751 Tank 1' -> 'Tank 1'."""
    desc = (description or "").strip()
    idx = desc.lower().rfind("tank")
    return desc[idx:].title() if idx >= 0 else desc


def next_sunday(today):
    """End of week = the coming Sunday. Returns (days_remaining, sunday_date)."""
    days = (6 - today.weekday()) % 7 or 7
    return days, today + timedelta(days=days)


# ── SVG: gauge ────────────────────────────────────────────────────────────────
#
# 240° arc, start 150° (lower-left) sweeping CW to 30° (lower-right) through the
# top. Angles use SVG y-down coords so increasing θ traces a CW arc (sweep=1).

import math

_GS = 150   # gauge start angle
_GT = 240   # gauge total sweep


def _arc(cx, cy, r, start_deg, sweep_deg):
    if sweep_deg <= 0:
        return ""
    s = math.radians(start_deg)
    e = math.radians(start_deg + sweep_deg)
    x1, y1 = cx + r * math.cos(s), cy + r * math.sin(s)
    x2, y2 = cx + r * math.cos(e), cy + r * math.sin(e)
    large = 1 if sweep_deg > 180 else 0
    return f"M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f}"


def gauge_svg(label, vol, cap, pct):
    if pct < 20:
        colour = RED
    elif pct < 40:
        colour = AMBER
    else:
        colour = GREEN

    cx, cy, r, sw = 100, 100, 72, 15
    frac_val = min(vol / cap, 1.0) if cap else 0
    frac_min = 0.20  # 20% low-level threshold

    bg_path  = _arc(cx, cy, r, _GS, _GT)
    val_path = _arc(cx, cy, r, _GS, frac_val * _GT)

    ta = math.radians(_GS + frac_min * _GT)
    r_in, r_out = r - sw * 0.6, r + sw * 0.6
    tx1, ty1 = cx + r_in * math.cos(ta), cy + r_in * math.sin(ta)
    tx2, ty2 = cx + r_out * math.cos(ta), cy + r_out * math.sin(ta)

    font = "-apple-system,BlinkMacSystemFont,sans-serif"
    return (
        '<svg viewBox="0 0 200 178" width="100%" style="display:block">'
        f'<path d="{bg_path}" fill="none" stroke="#252525" stroke-width="{sw}"/>'
        + (f'<path d="{val_path}" fill="none" stroke="{colour}" '
           f'stroke-width="{sw}" stroke-linecap="round"/>' if val_path else '')
        + f'<line x1="{tx1:.2f}" y1="{ty1:.2f}" x2="{tx2:.2f}" y2="{ty2:.2f}" '
          f'stroke="white" stroke-width="2.5" stroke-linecap="round"/>'
        + f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="38" '
          f'font-weight="700" fill="{colour}" font-family="{font}">{pct:.0f}%</text>'
        + f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="13" '
          f'fill="#aaa" font-family="{font}">{vol:,.0f} L</text>'
        + f'<text x="{cx}" y="170" text-anchor="middle" font-size="14" '
          f'font-weight="600" fill="white" font-family="{font}">{_html.escape(label)}</text>'
        + '</svg>'
    )


# ── SVG: bar charts ───────────────────────────────────────────────────────────

_FONT = "-apple-system,BlinkMacSystemFont,sans-serif"


def _svg_open(total_w, total_h):
    # Fixed CSS height + meet keeps proportions whether there are 3 bars or 31:
    # few bars render centred at natural size, many bars fill the width.
    return (
        f'<svg viewBox="0 0 {total_w} {total_h}" preserveAspectRatio="xMidYMid meet" '
        f'style="width:100%;height:{total_h}px;display:block" font-family="{_FONT}">'
    )


def bar_chart_svg(items, colour):
    """Vertical bar chart from a baseline at the bottom. items: [(label, value)]."""
    if not items:
        return '<p style="color:#777;font-style:italic">No data available.</p>'

    ml, mr, mt, mb = 16, 16, 28, 36
    slot, bar_w, plot_h = 34, 20, 260
    n = len(items)
    plot_w = n * slot
    total_w = ml + plot_w + mr
    total_h = mt + plot_h + mb
    max_val = max((v for _, v in items), default=0) or 1
    baseline = mt + plot_h

    parts = [_svg_open(total_w, total_h)]
    parts.append(f'<line x1="{ml}" y1="{baseline}" x2="{ml+plot_w}" y2="{baseline}" '
                 f'stroke="#2d4a5e" stroke-width="1"/>')
    for i, (label, value) in enumerate(items):
        bar_h = (value / max_val) * plot_h
        x = ml + i * slot + (slot - bar_w) / 2
        y = baseline - bar_h
        if value > 0:
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" '
                         f'height="{bar_h:.1f}" rx="2" fill="{colour}"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-5:.1f}" text-anchor="middle" '
                         f'font-size="10" fill="#ccc">{value:,.0f}</text>')
        parts.append(f'<text x="{x+bar_w/2:.1f}" y="{baseline+16:.1f}" text-anchor="middle" '
                     f'font-size="11" fill="#888">{_html.escape(str(label))}</text>')
    parts.append('</svg>')
    return "".join(parts)


def diff_chart_svg(items):
    """Diverging bar chart around a centre baseline. items: [(label, delta)].
    Positive (used more) = red above the line; negative (used less) = green below.
    """
    if not items:
        return '<p style="color:#777;font-style:italic">No data available.</p>'

    ml, mr, mt, mb = 16, 16, 24, 36
    slot, bar_w, plot_h = 34, 20, 280
    n = len(items)
    plot_w = n * slot
    total_w = ml + plot_w + mr
    total_h = mt + plot_h + mb
    half = plot_h / 2
    max_abs = max((abs(v) for _, v in items), default=0) or 1
    y0 = mt + half

    parts = [_svg_open(total_w, total_h)]
    for i, (label, value) in enumerate(items):
        bar_h = (abs(value) / max_abs) * half
        x = ml + i * slot + (slot - bar_w) / 2
        if value >= 0:
            y, colour, ty = y0 - bar_h, RED, y0 - bar_h - 4
        else:
            y, colour, ty = y0, GREEN, y0 + bar_h + 12
        if value != 0:
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" '
                         f'height="{bar_h:.1f}" rx="2" fill="{colour}"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{ty:.1f}" text-anchor="middle" '
                         f'font-size="9" fill="#aaa">{value:+,.0f}</text>')
        parts.append(f'<text x="{x+bar_w/2:.1f}" y="{mt+plot_h+16:.1f}" text-anchor="middle" '
                     f'font-size="11" fill="#888">{_html.escape(str(label))}</text>')
    parts.append(f'<line x1="{ml}" y1="{y0}" x2="{ml+plot_w}" y2="{y0}" '
                 f'stroke="#6a8499" stroke-width="1.5"/>')
    parts.append('</svg>')
    return "".join(parts)


# ── HTML sections ─────────────────────────────────────────────────────────────

def _gauges_html(tanks):
    cells = ""
    for t in tanks:
        vol = float(t["Volume"]); cap = float(t["Capacity"]); pct = float(t["Volume Percent"])
        cells += (f'<div class="gauge-cell">{gauge_svg(short_name(t["Description"]), vol, cap, pct)}'
                  f'<div class="gauge-meta">Status: <b>{_html.escape(str(t["Status"]))}</b><br>'
                  f'Updated: {_html.escape(str(t["Last Updated"]))}</div></div>')

    # Combined total of all tanks
    total_vol = sum(float(t["Volume"]) for t in tanks)
    total_cap = sum(float(t["Capacity"]) for t in tanks)
    total_pct = (total_vol / total_cap * 100) if total_cap else 0
    cells += (f'<div class="gauge-cell">{gauge_svg("Total", total_vol, total_cap, total_pct)}'
              f'<div class="gauge-meta">Combined of {len(tanks)} tanks<br>'
              f'Capacity: {total_cap:,.0f} L</div></div>')

    return f'<div class="gauges">{cells}</div>'


def _forecast_html(tanks, cur_consumption):
    today = datetime.now(AWST).date()
    days_to_sunday, sunday = next_sunday(today)

    rows, warnings = "", []
    for i, t in enumerate(tanks):
        tank_num = str(i + 1)
        vol = float(t["Volume"]); cap = float(t["Capacity"]); pct = float(t["Volume Percent"])
        vals = [v for v in cur_consumption.get(tank_num, {}).values() if v > 0]
        avg = sum(vals) / len(vals) if vals else 0
        projected = max(vol - avg * days_to_sunday, 0)
        proj_pct = (projected / cap * 100) if cap else 0
        dte = f"{vol / avg:.1f}" if avg > 0 else "N/A"

        cls = "row-red" if proj_pct < 20 else ("row-amber" if proj_pct < 40 else "")
        rows += (
            f'<tr class="{cls}">'
            f'<td class="td-name">{_html.escape(short_name(t["Description"]))}</td>'
            f'<td>{vol:,.0f}</td><td>{pct:.1f}%</td>'
            f'<td>{avg:,.0f}</td><td>{projected:,.0f}</td><td>{proj_pct:.1f}%</td>'
            f'<td>{dte}</td></tr>'
        )
        name = short_name(t["Description"])
        if proj_pct < 20:
            warnings.append(('warn', f'⚠️ {name} projected below 20% by end of week '
                                     f'({proj_pct:.1f}%). Consider ordering fuel.'))
        elif proj_pct < 40:
            warnings.append(('info', f'ℹ️ {name} projected at {proj_pct:.1f}% by end of week.'))

    table = (
        '<div style="overflow-x:auto"><table class="data-table"><thead><tr>'
        '<th>Tank</th><th>Current (L)</th><th>Current %</th><th>Avg Daily (L)</th>'
        '<th>Forecast EOW (L)</th><th>Forecast EOW %</th><th>Days to Empty</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
    )
    banners = "".join(
        f'<div class="banner banner-{kind}">{_html.escape(msg)}</div>' for kind, msg in warnings
    )
    caption = (f'<p class="caption">Forecast uses each tank\'s average daily consumption '
               f'(days with usage only). End of week = Sunday '
               f'<b>{sunday.strftime("%d %b %Y")}</b> ({days_to_sunday} day(s) remaining).</p>')
    return table + caption + banners


def _daily_usage_html(cur_consumption):
    dates = cur_consumption.get(PRIMARY_TANK, {})
    if not dates:
        return '<p style="color:#777;font-style:italic">No dip data this month yet.</p>', None
    items = [(d.day, v) for d, v in sorted(dates.items())]
    chart = bar_chart_svg(items, GOLD)
    used = [v for _, v in items if v > 0]
    avg = sum(used) / len(used) if used else 0
    total = sum(v for _, v in items)
    metrics = (
        '<div class="summary">'
        f'<div class="metric"><div class="metric-value">{avg:,.0f}</div>'
        '<div class="metric-label">Avg Daily (L)</div></div>'
        f'<div class="metric"><div class="metric-value">{total:,.0f}</div>'
        '<div class="metric-label">Month Total (L)</div></div></div>'
    )
    return chart, metrics


def _mom_html(cur_consumption, prev_consumption):
    today = datetime.now(AWST).date()
    cur_label = today.strftime("%B %Y")
    prev_label = (today.replace(day=1) - timedelta(days=1)).strftime("%B %Y")

    cur = cur_consumption.get(PRIMARY_TANK, {})
    prev = prev_consumption.get(PRIMARY_TANK, {})
    if not cur or not prev:
        return ('<p style="color:#777;font-style:italic">Insufficient data for '
                'month-on-month comparison.</p>')

    cur_by_day = defaultdict(float)
    prev_by_day = defaultdict(float)
    for d, v in cur.items():
        cur_by_day[d.day] += v
    for d, v in prev.items():
        prev_by_day[d.day] += v

    # Like-for-like: compare the elapsed days of this month against the SAME
    # days of last month (e.g. Jun 1-21 vs May 1-21), so all three figures
    # share one basis and reconcile (cur_avg - prev_avg == avg_delta).
    common = sorted(set(cur_by_day) & set(prev_by_day))
    items = [(day, cur_by_day[day] - prev_by_day[day]) for day in common]
    if not items:
        return ('<p style="color:#777;font-style:italic">No overlapping days to '
                'compare yet.</p>')

    cur_avg = sum(cur_by_day[d] for d in common) / len(common)
    prev_avg = sum(prev_by_day[d] for d in common) / len(common)
    avg_delta = cur_avg - prev_avg

    direction = "more" if avg_delta > 0 else "less"
    colour = RED if avg_delta > 0 else GREEN
    span = f"day {common[0]}" if len(common) == 1 else f"days {common[0]}–{common[-1]}"
    lead = (f'<p class="caption">On average <b style="color:{colour}">'
            f'{abs(avg_delta):,.0f} L/day {direction}</b> this month than {prev_label} '
            f'(comparing matching {span}).</p>')
    chart = diff_chart_svg(items)
    metrics = (
        '<div class="summary">'
        f'<div class="metric"><div class="metric-value">{cur_avg:,.0f}</div>'
        f'<div class="metric-label">Avg Daily ({cur_label[:3]})</div></div>'
        f'<div class="metric"><div class="metric-value">{prev_avg:,.0f}</div>'
        f'<div class="metric-label">Avg Daily ({prev_label[:3]})</div></div>'
        f'<div class="metric"><div class="metric-value">{avg_delta:+,.0f}</div>'
        '<div class="metric-label">Avg Daily Change (L)</div></div></div>'
    )
    legend = ('<p class="caption"><span style="color:%s">&#9632;</span> used more than '
              '%s &nbsp; <span style="color:%s">&#9632;</span> used less</p>'
              % (RED, prev_label, GREEN))
    return lead + chart + legend + metrics


# ── Page ──────────────────────────────────────────────────────────────────────

STYLE = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0e1117; color: #fff; padding: 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .header { background: #083045; padding: 16px 20px; border-radius: 8px; margin-bottom: 16px; }
    .header-sub { font-size: 11px; font-weight: 700; text-transform: uppercase;
      letter-spacing: .1em; color: rgba(255,255,255,.6); margin-bottom: 4px; }
    .header-title { font-size: 20px; font-weight: 700; }
    .header-date { font-size: 13px; color: rgba(255,255,255,.7); margin-top: 4px; }
    .header-eow { font-size: 13px; color: #B19045; font-weight: 600; margin-top: 4px; }
    .divider { border: none; border-top: 2px solid #2d4a5e; margin: 28px 0; }
    .section-title { font-size: 17px; font-weight: 700; margin-bottom: 12px; }
    .gauges { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; }
    .gauge-cell { flex: 1; min-width: 160px; max-width: 280px;
      background: #11161d; border-radius: 8px; padding: 10px; }
    .gauge-meta { text-align: center; font-size: 12px; color: rgba(255,255,255,.7); margin-top: 4px; }
    .summary { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .metric { flex: 1; min-width: 110px; background: #083045; border-radius: 8px;
      padding: 14px 10px; text-align: center; }
    .metric-value { font-size: 30px; font-weight: 700; line-height: 1; }
    .metric-label { font-size: 12px; color: rgba(255,255,255,.7); margin-top: 6px; }
    .data-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .data-table th { text-align: left; padding: 8px 10px; font-size: 13px;
      border-bottom: 2px solid #2a2a2a; color: rgba(255,255,255,.8); white-space: nowrap; }
    .data-table td { padding: 8px 10px; border-bottom: 1px solid #1a1a1a; white-space: nowrap; }
    .data-table .td-name { font-weight: 600; }
    .row-red td { background: rgba(231,76,60,.14); }
    .row-amber td { background: rgba(243,156,18,.12); }
    .caption { font-size: 12px; color: #999; margin: 10px 0; }
    .banner { border-radius: 6px; padding: 10px 12px; font-size: 13px; margin-top: 8px; }
    .banner-warn { background: rgba(231,76,60,.18); border-left: 3px solid #e74c3c; }
    .banner-info { background: rgba(243,156,18,.15); border-left: 3px solid #f39c12; }
    .footer { text-align: center; color: #555; font-size: 11px; margin-top: 28px;
      padding-bottom: 12px; line-height: 1.8; }
"""


def build_html(tanks, cur_consumption, prev_consumption):
    now = datetime.now(AWST)
    date_str = now.strftime("%A, %d %B %Y")
    gen_str = now.strftime("%d %b %Y, %I:%M %p AWST").lstrip("0")
    _, sunday = next_sunday(now.date())
    eow_str = sunday.strftime("%a %d %b %Y")

    gauges = _gauges_html(tanks)
    forecast = _forecast_html(tanks, cur_consumption)
    usage_chart, usage_metrics = _daily_usage_html(cur_consumption)
    mom = _mom_html(cur_consumption, prev_consumption)
    cur_month = now.strftime("%B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>NMG Crown Prince — Fuel Dashboard</title>
  <style>{STYLE}</style>
</head>
<body>

  <div class="header">
    <div class="header-sub">New Murchison Gold &mdash; Crown Prince Operation</div>
    <div class="header-title">&#9981; Fuel Dashboard</div>
    <div class="header-date">{date_str}</div>
    <div class="header-eow">End-of-week forecast date: <b>{eow_str}</b></div>
  </div>

  <div class="section-title">Current Tank Levels</div>
  {gauges}

  <hr class="divider">

  <div class="section-title">Daily Usage &mdash; {cur_month} (Tank 1)</div>
  {usage_chart}
  {usage_metrics or ""}

  <hr class="divider">

  <div class="section-title">End-of-Week Forecast</div>
  {forecast}

  <hr class="divider">

  <div class="section-title">Month-on-Month Daily Usage (Tank 1)</div>
  {mom}

  <div class="footer">
    Generated automatically &mdash; NMG Fuel System &mdash; Source: SmartFill<br>
    Last updated: {gen_str}
  </div>

</body>
</html>"""


def main():
    print("Fetching fuel data from SmartFill...", end=" ", flush=True)
    tanks = get_tank_levels()
    cur_consumption = calc_daily_consumption(get_dips("Current Month"))
    prev_consumption = calc_daily_consumption(get_dips("Previous Month"))
    print(f"done. {len(tanks)} tank(s).")

    html = build_html(tanks, cur_consumption, prev_consumption)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written: {OUT_PATH}")


if __name__ == "__main__":
    main()
