import requests
import os

try:
    import streamlit as st
    CLIENT_REF = st.secrets["SMARTFILL_CLIENT_REF"]
    CLIENT_SECRET = st.secrets["SMARTFILL_CLIENT_SECRET"]
except Exception:
    CLIENT_REF = os.environ.get("SMARTFILL_CLIENT_REF", "")
    CLIENT_SECRET = os.environ.get("SMARTFILL_CLIENT_SECRET", "")

API_URL = "https://www.fmtdata.com/API/api.php"
TANK_CAPACITY = 110000  # litres


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
    r = requests.post(API_URL, json=payload, headers={"Content-Type": "application/json-rpc"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    return data["result"]


def get_tank_levels():
    """Returns list of dicts with tank data."""
    result = _call("Tank:Level", {
        "columns": ["Description", "Volume", "Volume Percent", "Capacity", "Status", "Last Updated", "Timezone"]
    })
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["values"]]


def get_transactions(period="Current Week"):
    """Returns list of dicts with transaction data."""
    result = _call("Transactions:Read", {
        "columns": ["Date", "Source Tank", "Volume", "Volumetric Unit"],
        "period": {"type": "recurring", "value": period},
        "order": [{"Date": "ASC"}],
    })
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result.get("data", result.get("values", []))]


def get_tank_dips(period="Current Month"):
    """Returns list of dicts with dip history per tank.
    Fields: Date, Time, Tank Number, Record Type, Volume.
    """
    result = _call("Tank:Read", {
        "columns": ["Date", "Time", "Tank Number", "Record Type", "Volume", "Volumetric Units"],
        "period": {"type": "recurring", "value": period},
        "order": [{"Date": "ASC"}, {"Time": "ASC"}],
    })
    cols = result["columns"]
    rows = result.get("data", result.get("values", []))
    return [dict(zip(cols, row)) for row in rows]
