"""
Crown Prince Gold Mine — Daily Fuel Export (GitHub Actions)
Runs at 7am AWST daily. Produces 4 CSV files matching the dashboard:
  data/tank_levels.csv      — appended daily (running history)
  data/daily_usage.csv      — current month daily consumption per tank (replaced daily)
  data/forecast.csv         — end-of-week forecast snapshot (replaced daily)
  data/mom_comparison.csv   — month-on-month daily comparison (replaced daily)
"""

import requests
import csv
import os
from datetime import datetime, timedelta
from collections import defaultdict

API_URL = "https://www.fmtdata.com/API/api.php"
CLIENT_REF = os.environ.get("SMARTFILL_CLIENT_REF", "")
CLIENT_SECRET = os.environ.get("SMARTFILL_CLIENT_SECRET", "")

os.makedirs("data", exist_ok=True)

LEVELS_PATH  = "data/tank_levels.csv"
USAGE_PATH   = "data/daily_usage.csv"
FORECAST_PATH = "data/forecast.csv"
MOM_PATH     = "data/mom_comparison.csv"


# ── API helpers ───────────────────────────────────────────────────────────────

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
    r = requests.post(API_URL, json=payload,
                      headers={"Content-Type": "application/json-rpc"}, timeout=15)
    r.raise_for_status()
    data = r.json()
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


# ── Consumption calculator ────────────────────────────────────────────────────

def calc_daily_consumption(dips):
    """Returns dict: {tank_num: {date_str: consumed_litres}}"""
    by_tank_date = defaultdict(lambda: defaultdict(list))
    for row in dips:
        if row.get("Record Type", "").strip().lower() != "dip":
            continue
        try:
            dt = datetime.strptime(row["Date"] + " " + row["Time"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        by_tank_date[row["Tank Number"]][dt.date()].append((dt, float(row["Volume"])))

    result = defaultdict(dict)
    for tank_num, dates in by_tank_date.items():
        for date, readings in dates.items():
            readings.sort()
            consumed = max(readings[0][1] - readings[-1][1], 0)
            result[tank_num][date] = consumed
    return result


# ── 1. Tank levels (append) ───────────────────────────────────────────────────

def write_tank_levels(tanks, today_str):
    fieldnames = ["Date", "Tank", "Volume (L)", "Volume %",
                  "Capacity (L)", "Status", "Last Updated"]
    file_exists = os.path.isfile(LEVELS_PATH)

    # Skip if today already written
    if file_exists:
        with open(LEVELS_PATH) as f:
            if today_str in f.read():
                print("Tank levels already written today — skipping.")
                return

    with open(LEVELS_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for tank in tanks:
            writer.writerow({
                "Date": today_str,
                "Tank": tank["Description"],
                "Volume (L)": float(tank["Volume"]),
                "Volume %": float(tank["Volume Percent"]),
                "Capacity (L)": float(tank["Capacity"]),
                "Status": tank["Status"],
                "Last Updated": tank["Last Updated"],
            })
    print(f"Tank levels written — {len(tanks)} rows.")


# ── 2. Daily usage current month (replace) ───────────────────────────────────

def write_daily_usage(cur_consumption, today_str):
    fieldnames = ["Snapshot Date", "Date", "Tank", "Consumed (L)"]
    rows = []
    for tank_num, dates in cur_consumption.items():
        for date, consumed in sorted(dates.items()):
            rows.append({
                "Snapshot Date": today_str,
                "Date": date.strftime("%d/%m/%Y"),
                "Tank": f"Tank {tank_num}",
                "Consumed (L)": round(consumed),
            })

    with open(USAGE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Daily usage written — {len(rows)} rows.")


# ── 3. End-of-week forecast (replace) ────────────────────────────────────────

def write_forecast(tanks, cur_consumption, today_str):
    today = datetime.now().date()
    days_to_sunday = (6 - today.weekday()) % 7 or 7
    sunday = today + timedelta(days=days_to_sunday)

    # Average daily usage per tank (days with consumption only)
    tank_avgs = {}
    for tank_num, dates in cur_consumption.items():
        values = [v for v in dates.values() if v > 0]
        tank_avgs[tank_num] = sum(values) / len(values) if values else 0

    fieldnames = ["Snapshot Date", "Tank", "Current (L)", "Current %",
                  "Avg Daily Usage (L)", "Forecast EOW (L)", "Forecast EOW %",
                  "Days Until Empty", "EOW Date"]
    rows = []
    for i, tank in enumerate(tanks):
        tank_num = str(i + 1)
        vol = float(tank["Volume"])
        cap = float(tank["Capacity"])
        pct_now = float(tank["Volume Percent"])
        avg = tank_avgs.get(tank_num, 0)
        projected = max(vol - avg * days_to_sunday, 0)
        proj_pct = (projected / cap * 100) if cap > 0 else 0
        days_until_empty = vol / avg if avg > 0 else None

        rows.append({
            "Snapshot Date": today_str,
            "Tank": tank["Description"],
            "Current (L)": round(vol),
            "Current %": round(pct_now, 1),
            "Avg Daily Usage (L)": round(avg),
            "Forecast EOW (L)": round(projected),
            "Forecast EOW %": round(proj_pct, 1),
            "Days Until Empty": round(days_until_empty, 1) if days_until_empty else "N/A",
            "EOW Date": sunday.strftime("%d/%m/%Y"),
        })

    with open(FORECAST_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Forecast written — {len(rows)} rows.")


# ── 4. Month-on-month comparison (replace) ───────────────────────────────────

def write_mom_comparison(cur_consumption, prev_consumption, today_str):
    today = datetime.now().date()
    cur_label = today.strftime("%B %Y")
    prev_label = (today.replace(day=1) - timedelta(days=1)).strftime("%B %Y")

    all_tanks = sorted(set(list(cur_consumption.keys()) + list(prev_consumption.keys())))
    fieldnames = ["Snapshot Date", "Tank", "Day",
                  f"{cur_label} (L)", f"{prev_label} (L)", "Difference (L)"]
    rows = []
    for tank_num in all_tanks:
        cur_dates = cur_consumption.get(tank_num, {})
        prev_dates = prev_consumption.get(tank_num, {})
        all_days = sorted(set(
            [d.day for d in cur_dates.keys()] +
            [d.day for d in prev_dates.keys()]
        ))
        cur_by_day = {d.day: v for d, v in cur_dates.items()}
        prev_by_day = {d.day: v for d, v in prev_dates.items()}
        for day in all_days:
            cur_val = cur_by_day.get(day, 0)
            prev_val = prev_by_day.get(day, 0)
            rows.append({
                "Snapshot Date": today_str,
                "Tank": f"Tank {tank_num}",
                "Day": day,
                f"{cur_label} (L)": round(cur_val),
                f"{prev_label} (L)": round(prev_val),
                "Difference (L)": round(cur_val - prev_val),
            })

    with open(MOM_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Month-on-month comparison written — {len(rows)} rows.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today_str = datetime.now().strftime("%d/%m/%Y")
    print(f"Running export for {today_str}...")

    tanks = get_tank_levels()
    cur_dips = get_dips("Current Month")
    prev_dips = get_dips("Previous Month")

    cur_consumption = calc_daily_consumption(cur_dips)
    prev_consumption = calc_daily_consumption(prev_dips)

    write_tank_levels(tanks, today_str)
    write_daily_usage(cur_consumption, today_str)
    write_forecast(tanks, cur_consumption, today_str)
    write_mom_comparison(cur_consumption, prev_consumption, today_str)

    print("Export complete.")


if __name__ == "__main__":
    main()
