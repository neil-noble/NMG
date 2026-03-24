import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import api

st.set_page_config(
    page_title="Crown Prince Gold Mine — Fuel Dashboard",
    page_icon="⛽",
    layout="wide",
)

st.title("Crown Prince Gold Mine — Fuel Dashboard")
st.markdown("*Created by Neil Noble. NMG HSE Consultant. Emergency Services Australia.*")
st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y %H:%M')}")

# ── Fetch data ────────────────────────────────────────────────────────────────
with st.spinner("Loading data..."):
    try:
        tanks = api.get_tank_levels()
        dips = api.get_tank_dips("Current Month")
        dips_prev = api.get_tank_dips("Previous Month")
    except Exception as e:
        st.error(f"API error: {e}")
        st.stop()

# ── Write CSV for Excel Power Query ───────────────────────────────────────────
import os, csv

CSV_PATH = r"P:\GardenGully\Crown Prince Operations\02_Engineering\03_Production\11_Daily Report\fuel_data.csv"

def write_csv(tanks, dips):
    daily = calc_daily_consumption(dips)
    today_str = datetime.now().strftime("%d/%m/%Y")
    rows = []
    for tank in tanks:
        name = tank["Description"]
        vol = float(tank["Volume"])
        pct = float(tank["Volume Percent"])
        cap = float(tank["Capacity"])
        status = tank["Status"]
        updated = tank["Last Updated"]
        tank_key = name.strip()[-1] if name.strip()[-1].isdigit() else ""
        tank_label = f"Tank {tank_key}"
        today_usage = 0
        if not daily.empty:
            today_date = datetime.now().date()
            mask = (daily["Tank"] == tank_label) & (pd.to_datetime(daily["Date"]).dt.date == today_date)
            if mask.any():
                today_usage = daily.loc[mask, "Consumed (L)"].values[0]
        rows.append({
            "Date": today_str,
            "Tank": name,
            "Volume (L)": vol,
            "Volume %": pct,
            "Capacity (L)": cap,
            "Status": status,
            "Last Updated": updated,
            "Today Usage (L)": today_usage,
        })

    file_exists = os.path.isfile(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        # Only append if today's date not already written
        if file_exists:
            with open(CSV_PATH, "r") as rf:
                existing = rf.read()
            if today_str in existing:
                return
        writer.writerows(rows)

write_csv(tanks, dips)

# ── Current tank levels ───────────────────────────────────────────────────────
st.subheader("Current Tank Levels")

TANK_COLOURS = {"1": "#083045", "2": "#B19045"}

cols = st.columns(len(tanks))
for col, tank in zip(cols, tanks):
    vol = float(tank["Volume"])
    pct = float(tank["Volume Percent"])
    cap = float(tank["Capacity"])
    status = tank["Status"]
    name = tank["Description"]
    updated = tank["Last Updated"]

    if pct < 20:
        colour = "#e74c3c"  # red
    elif pct < 40:
        colour = "#f39c12"  # amber
    else:
        colour = "#27ae60"  # green

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=vol,
        number={"suffix": " L", "valueformat": ",.0f"},
        delta={"reference": cap, "valueformat": ",.0f", "suffix": " L"},
        title={"text": name, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, cap], "tickformat": ",.0f"},
            "bar": {"color": colour},
            "steps": [
                {"range": [0, cap * 0.2], "color": "#fadbd8"},
                {"range": [cap * 0.2, cap * 0.4], "color": "#fdebd0"},
                {"range": [cap * 0.4, cap], "color": "#d5f5e3"},
            ],
            "threshold": {
                "line": {"color": "red", "width": 2},
                "thickness": 0.75,
                "value": cap * 0.2,
            },
        },
    ))
    fig.update_layout(height=280, margin=dict(t=40, b=10, l=20, r=20))

    with col:
        st.plotly_chart(fig, use_container_width=True)
        st.metric("Volume", f"{vol:,.0f} L", f"{pct:.1f}% full")
        st.caption(f"Status: **{status}** | Updated: {updated}")

st.divider()

# ── Build per-tank daily consumption from dip history ────────────────────────
def calc_daily_consumption(dips):
    """
    From raw dip rows, compute daily consumption per tank.
    Strategy: for each tank+day, take first and last dip reading.
    Consumption = first_volume - last_volume (positive = consumed).
    Negative values (deliveries) are set to 0 for that day.
    """
    if not dips:
        return pd.DataFrame()

    df = pd.DataFrame(dips)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
    df["DateTime"] = pd.to_datetime(df["Date"] + " " + df["Time"], errors="coerce")
    df = df[df["DateTime"].notna()]
    df["Date"] = df["DateTime"].dt.date
    df["Tank Number"] = df["Tank Number"].astype(str)

    # Keep only Dip records
    if "Record Type" in df.columns:
        df = df[df["Record Type"].str.strip().str.lower() == "dip"]

    result_rows = []
    for (tank, date), group in df.groupby(["Tank Number", "Date"]):
        group = group.sort_values("DateTime")
        first_vol = group.iloc[0]["Volume"]
        last_vol = group.iloc[-1]["Volume"]
        consumed = first_vol - last_vol
        if consumed < 0:
            consumed = 0  # delivery or re-fill — not consumption
        result_rows.append({"Date": date, "Tank": f"Tank {tank}", "Consumed (L)": consumed})

    return pd.DataFrame(result_rows)

daily_df = calc_daily_consumption(dips)

# ── Daily usage ───────────────────────────────────────────────────────────────
st.subheader("Daily Usage — Current Month (per Tank)")

if daily_df.empty:
    st.info("No dip data this month yet.")
else:
    daily_df["Date"] = pd.to_datetime(daily_df["Date"])
    daily_df["Date_str"] = daily_df["Date"].dt.strftime("%a %d %b")

    tank_names = sorted(daily_df["Tank"].unique())

    chart_cols = st.columns(len(tank_names))
    for chart_col, tank_name in zip(chart_cols, tank_names):
        t_df = daily_df[daily_df["Tank"] == tank_name].sort_values("Date")
        key = tank_name.strip()[-1] if tank_name.strip()[-1].isdigit() else ""
        colour = TANK_COLOURS.get(key, "#083045")

        fig_t = go.Figure(go.Bar(
            x=t_df["Date_str"],
            y=t_df["Consumed (L)"],
            marker_color=colour,
            text=t_df["Consumed (L)"].apply(lambda v: f"{v:,.0f} L"),
            textposition="outside",
        ))
        fig_t.update_layout(
            title={"text": tank_name, "font": {"color": colour}},
            yaxis_title="Litres",
            height=360,
            margin=dict(t=40, b=20, l=20, r=20),
            yaxis={"tickformat": ",.0f"},
            showlegend=False,
        )

        t_data = t_df["Consumed (L)"]
        avg = t_data[t_data > 0].mean() if (t_data > 0).any() else 0
        total = t_data.sum()

        with chart_col:
            st.plotly_chart(fig_t, use_container_width=True)
            c1, c2 = st.columns(2)
            c1.metric("Avg Daily", f"{avg:,.0f} L")
            c2.metric("Month Total", f"{total:,.0f} L")

st.divider()

# ── End-of-week forecast ─────────────────────────────────────────────────────
st.subheader("End-of-Week Forecast (Sunday)")

if daily_df.empty:
    st.info("Insufficient data for forecast.")
else:
    today = datetime.now().date()
    days_to_sunday = (6 - today.weekday()) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7
    sunday = today + timedelta(days=days_to_sunday)
    days_remaining = days_to_sunday

    # Average daily consumption per tank (only days with actual consumption)
    tank_avgs = {}
    for tank_name in tank_names:
        t_data = daily_df[daily_df["Tank"] == tank_name]["Consumed (L)"]
        tank_avgs[tank_name] = t_data[t_data > 0].mean() if (t_data > 0).any() else 0

    forecast_rows = []
    for tank in tanks:
        name = tank["Description"]
        vol = float(tank["Volume"])
        cap = float(tank["Capacity"])
        pct_now = float(tank["Volume Percent"])

        tank_num = tank_names[tanks.index(tank) % len(tank_names)]

        avg = tank_avgs.get(tank_num, 0)
        projected = max(vol - avg * days_remaining, 0)
        proj_pct = (projected / cap) * 100
        days_until_empty = vol / avg if avg > 0 else float("inf")

        forecast_rows.append({
            "Tank": name,
            "Current (L)": f"{vol:,.0f}",
            "Current %": f"{pct_now:.1f}%",
            "Avg Daily Usage (L)": f"{avg:,.0f}",
            "Forecast EOW (L)": f"{projected:,.0f}",
            "Forecast EOW %": f"{proj_pct:.1f}%",
            "Days until empty": f"{days_until_empty:.1f}" if days_until_empty != float("inf") else "N/A",
            "_proj_pct": proj_pct,
            "_tank_num": tank_num,
        })

    forecast_df = pd.DataFrame(forecast_rows)

    def colour_row(row):
        # _tank_num is e.g. "Tank 1" — extract the digit to look up TANK_COLOURS
        key = row["_tank_num"].strip()[-1] if row["_tank_num"].strip()[-1].isdigit() else ""
        base = TANK_COLOURS.get(key, "")
        return [f"background-color: {base}"] * len(row) if base else [""] * len(row)

    st.dataframe(
        forecast_df.style.apply(colour_row, axis=1).hide(subset=["_proj_pct", "_tank_num"], axis="columns"),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Forecast based on per-tank avg daily consumption (days with usage only). "
        f"End of week = Sunday **{sunday.strftime('%d %b %Y')}** ({days_remaining} day(s) remaining)."
    )

    for row in forecast_rows:
        if row["_proj_pct"] < 20:
            st.warning(f"⚠️ {row['Tank']} projected to be below 20% by end of week ({row['Forecast EOW %']}). Consider ordering fuel.")
        elif row["_proj_pct"] < 40:
            st.info(f"ℹ️ {row['Tank']} projected to be at {row['Forecast EOW %']} by end of week.")

st.divider()

# ── Month-on-month comparison ─────────────────────────────────────────────────
st.subheader("Month-on-Month Daily Usage Comparison")

prev_df = calc_daily_consumption(dips_prev)

if daily_df.empty or prev_df.empty:
    st.info("Insufficient data for month-on-month comparison.")
else:
    today = datetime.now().date()
    cur_label = today.strftime("%B %Y")
    prev_month = (today.replace(day=1) - timedelta(days=1))
    prev_label = prev_month.strftime("%B %Y")

    # Add day-of-month for x-axis alignment
    daily_df["Day"] = pd.to_datetime(daily_df["Date"]).dt.day
    prev_df["Date"] = pd.to_datetime(prev_df["Date"])
    prev_df["Day"] = prev_df["Date"].dt.day

    cmp_cols = st.columns(len(tank_names) + 1)
    for cmp_col, tank_name in zip(cmp_cols, tank_names):
        key = tank_name.strip()[-1] if tank_name.strip()[-1].isdigit() else ""
        colour = TANK_COLOURS.get(key, "#083045")

        cur = daily_df[daily_df["Tank"] == tank_name].sort_values("Day")
        prv = prev_df[prev_df["Tank"] == tank_name].sort_values("Day")

        diff = (
            pd.merge(
                cur[["Day", "Consumed (L)"]].rename(columns={"Consumed (L)": "cur"}),
                prv[["Day", "Consumed (L)"]].rename(columns={"Consumed (L)": "prv"}),
                on="Day", how="inner",
            ).sort_values("Day")
        )
        diff["delta"] = diff["cur"] - diff["prv"]
        diff["bar_colour"] = diff["delta"].apply(lambda v: "#e74c3c" if v > 0 else "#27ae60")

        avg_delta = diff["delta"].mean()
        cur_avg = cur["Consumed (L)"][cur["Consumed (L)"] > 0].mean() if (cur["Consumed (L)"] > 0).any() else 0
        prv_avg = prv["Consumed (L)"][prv["Consumed (L)"] > 0].mean() if (prv["Consumed (L)"] > 0).any() else 0

        fig_cmp = go.Figure()
        fig_cmp.add_trace(go.Bar(
            name="Difference",
            x=diff["Day"],
            y=diff["delta"],
            marker_color=diff["bar_colour"],
            hovertemplate="Day %{x}<br>%{y:+,.0f} L<extra></extra>",
        ))
        fig_cmp.add_hline(y=0, line_color="white", line_width=1)
        fig_cmp.update_layout(
            title={"text": tank_name, "font": {"color": colour}},
            xaxis={"title": "Day of Month", "dtick": 1},
            yaxis={"title": f"Litres vs {prev_label}", "tickformat": "+,.0f"},
            height=360,
            margin=dict(t=40, b=20, l=20, r=20),
            showlegend=False,
            hovermode="x",
        )

        with cmp_col:
            direction = "more" if avg_delta > 0 else "less"
            colour_word = "red" if avg_delta > 0 else "green"
            st.markdown(
                f"**{tank_name}** — on average :{colour_word}[**{abs(avg_delta):,.0f} L/day {direction}**] "
                f"this month than {prev_label}"
            )
            st.plotly_chart(fig_cmp, use_container_width=True)
            c1, c2, c3 = st.columns(3)
            c1.metric(f"Avg Daily ({cur_label[:3]})", f"{cur_avg:,.0f} L")
            c2.metric(f"Avg Daily ({prev_label[:3]})", f"{prv_avg:,.0f} L")
            c3.metric("Avg Daily Change", f"{avg_delta:+,.0f} L")

    # ── Combined both tanks ───────────────────────────────────────────────────
    cur_all = daily_df.groupby("Day")["Consumed (L)"].sum().reset_index()
    prv_all = prev_df.groupby("Day")["Consumed (L)"].sum().reset_index()

    diff_all = (
        pd.merge(
            cur_all.rename(columns={"Consumed (L)": "cur"}),
            prv_all.rename(columns={"Consumed (L)": "prv"}),
            on="Day", how="inner",
        ).sort_values("Day")
    )
    diff_all["delta"] = diff_all["cur"] - diff_all["prv"]
    diff_all["bar_colour"] = diff_all["delta"].apply(lambda v: "#e74c3c" if v > 0 else "#27ae60")

    avg_delta_all = diff_all["delta"].mean()
    cur_avg_all = cur_all["Consumed (L)"].mean()
    prv_avg_all = prv_all["Consumed (L)"].mean()

    fig_all = go.Figure()
    fig_all.add_trace(go.Bar(
        name="Difference",
        x=diff_all["Day"],
        y=diff_all["delta"],
        marker_color=diff_all["bar_colour"],
        hovertemplate="Day %{x}<br>%{y:+,.0f} L<extra></extra>",
    ))
    fig_all.add_hline(y=0, line_color="white", line_width=1)
    fig_all.update_layout(
        title={"text": "Both Tanks Combined"},
        xaxis={"title": "Day of Month", "dtick": 1},
        yaxis={"title": f"Litres vs {prev_label}", "tickformat": "+,.0f"},
        height=360,
        margin=dict(t=40, b=20, l=20, r=20),
        showlegend=False,
        hovermode="x",
    )

    with cmp_cols[-1]:
        direction_all = "more" if avg_delta_all > 0 else "less"
        colour_word_all = "red" if avg_delta_all > 0 else "green"
        st.markdown(
            f"**Both Tanks** — on average :{colour_word_all}[**{abs(avg_delta_all):,.0f} L/day {direction_all}**] "
            f"this month than {prev_label}"
        )
        st.plotly_chart(fig_all, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Avg Daily ({cur_label[:3]})", f"{cur_avg_all:,.0f} L")
        c2.metric(f"Avg Daily ({prev_label[:3]})", f"{prv_avg_all:,.0f} L")
        c3.metric("Avg Daily Change", f"{avg_delta_all:+,.0f} L")
