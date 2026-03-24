"""
Crown Prince Gold Mine — Daily Fuel Export (GitHub Actions)
Runs at 7am AWST daily via GitHub Actions.
Appends one row per tank to fuel_data.csv in the repository.
"""

import requests
import csv
import os
from datetime import datetime
from collections import defaultdict

import os

API_URL = "https://www.fmtdata.com/API/api.php"
CLIENT_REF = os.environ.get("SMARTFILL_CLIENT_REF", "")
CLIENT_SECRET = os.environ.get("SMARTFILL_CLIENT_SECRET", "")

CSV_PATH = "fuel_data.csv"

FIELDNAMES = [
    "Date",
    "Tank",
    "Volume (L)",
    "Volume %",
    "Capacity (L)",
    "Status",
    "Last Updated",
    "Today Usage (L)",
]


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
    r = requests.post(
        API_URL,
        json=payload,
        headers={"Content-Type": "application/json-rpc"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    return data["result"]


def get_tank_levels():
    result = _call("Tank:Level", {
        "columns": ["Description", "Volume", "Volume Percent", "Capacity", "Status", "Last Updated"],
    })
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["values"]]


def get_today_usage():
    result = _call("Tank:Read", {
        "columns": ["Date", "Time", "Tank Number", "Record Type", "Volume"],
        "period": {"type": "recurring", "value": "Today"},
        "order": [{"Date": "ASC"}, {"Time": "ASC"}],
    })
    cols = result["columns"]
    rows = [dict(zip(cols, row)) for row in result.get("data", result.get("values", []))]

    by_tank = defaultdict(list)
    for row in rows:
        if row.get("Record Type", "").strip().lower() == "dip":
            by_tank[row["Tank Number"]].append(float(row["Volume"]))

    return {
        tank_num: max(volumes[0] - volumes[-1], 0)
        for tank_num, volumes in by_tank.items()
        if len(volumes) >= 2
    }


def already_written(today_str):
    if not os.path.isfile(CSV_PATH):
        return False
    with open(CSV_PATH, "r") as f:
        return today_str in f.read()


def main():
    today_str = datetime.now().strftime("%d/%m/%Y")

    if already_written(today_str):
        print(f"{today_str} already written — skipping.")
        return

    tanks = get_tank_levels()
    usage = get_today_usage()

    file_exists = os.path.isfile(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for i, tank in enumerate(tanks):
            tank_num = str(i + 1)
            writer.writerow({
                "Date": today_str,
                "Tank": tank["Description"],
                "Volume (L)": float(tank["Volume"]),
                "Volume %": float(tank["Volume Percent"]),
                "Capacity (L)": float(tank["Capacity"]),
                "Status": tank["Status"],
                "Last Updated": tank["Last Updated"],
                "Today Usage (L)": usage.get(tank_num, 0),
            })

    print(f"{today_str} — written {len(tanks)} rows to {CSV_PATH}")


if __name__ == "__main__":
    main()
