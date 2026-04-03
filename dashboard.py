import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import api

st.set_page_config(
    page_title="NMG — Crown Prince Gold Mine — Fuel Dashboard",
    page_icon="⛽",
    layout="wide",
)

st.title("NMG — Crown Prince Gold Mine — Fuel Dashboard")
st.markdown("Created by Neil Noble. NMG HSE Consultant.")
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

# ── Current tank levels ───────────────────────────────────────────────────────
st.subheader("Current Tank Levels")

total_vol = sum(float(t["Volume"]) for t in tanks)
total_cap = sum(float(t["Capacity"]) for t in tanks)
total_pct = (total_vol / total_cap * 100) if total_cap > 0 else 0

if total_pct < 20:
    colour = "#e74c3c"
elif total_pct < 40:
    colour = "#f39c12"
else:
    colour = "#27ae60"

fig = go.Figure(go.Indicator(
    mode="gauge+number+delta",
    value=total_vol,
    number={"suffix": " L", "valueformat": ",.0f"},
    delta={"reference": total_cap, "valueformat": ",.0f", "suffix": " L"},
    title={"text": "Combined Tank Level", "font": {"size": 14}},
    gauge={
        "axis": {"range": [0, total_cap], "tickformat": ",.0f"},
        "bar": {"color": colour},
        "steps": [
            {"range": [0, total_cap * 0.2], "color": "#fadbd8"},
            {"range": [total_cap * 0.2, total_cap * 0.4], "color": "#fdebd0"},
            {"range": [total_cap * 0.4, total_cap], "color": "#d5f5e3"},
        ],
        "threshold": {
            "line": {"color": "red", "width": 2},
            "thickness": 0.75,
            "value": total_cap * 0.2,
        },
    },
))
fig.update_layout(height=280, margin=dict(t=40, b=10, l=20, r=20))

col_gauge, col_spacer = st.columns([1, 2])
with col_gauge:
    st.plotly_chart(fig, use_container_width=True)
    st.metric("Total Volume", f"{total_vol:,.0f} L", f"{total_pct:.1f}% full")
    st.caption(f"Capacity: {total_cap:,.0f} L across {len(tanks)} tanks")

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
st.subheader("Daily Usage — Current Month (Tank 1)")

if daily_df.empty:
    st.info("No dip data this month yet.")
else:
    daily_df["Date"] = pd.to_datetime(daily_df["Date"])
    daily_df["Date_str"] = daily_df["Date"].dt.strftime("%a %d %b")

    tank1_daily = daily_df[daily_df["Tank"] == "Tank 1"].sort_values("Date")

    combined_df = daily_df.groupby(["Date", "Date_str"], as_index=False)["Consumed (L)"].sum().sort_values("Date")

    fig_t = go.Figure(go.Bar(
        x=tank1_daily["Date_str"],
        y=tank1_daily["Consumed (L)"],
        marker_color="#083045",
        text=tank1_daily["Consumed (L)"].apply(lambda v: f"{v:,.0f} L"),
        textposition="outside",
    ))
    fig_t.update_layout(
        yaxis_title="Litres",
        height=360,
        margin=dict(t=40, b=20, l=20, r=20),
        yaxis={"tickformat": ",.0f"},
        showlegend=False,
    )

    tank1_data = tank1_daily["Consumed (L)"]
    avg = tank1_data[tank1_data > 0].mean() if (tank1_data > 0).any() else 0
    total = tank1_data.sum()

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

    # Average daily combined consumption (only days with actual consumption)
    combined_data = combined_df["Consumed (L)"]
    avg_combined = combined_data[combined_data > 0].mean() if (combined_data > 0).any() else 0

    projected = max(total_vol - avg_combined * days_remaining, 0)
    proj_pct = (projected / total_cap * 100) if total_cap > 0 else 0
    days_until_empty = total_vol / avg_combined if avg_combined > 0 else float("inf")

    forecast_df = pd.DataFrame([{
        "Current (L)": f"{total_vol:,.0f}",
        "Current %": f"{total_pct:.1f}%",
        "Avg Daily Usage (L)": f"{avg_combined:,.0f}",
        "Forecast EOW (L)": f"{projected:,.0f}",
        "Forecast EOW %": f"{proj_pct:.1f}%",
        "Days until empty": f"{days_until_empty:.1f}" if days_until_empty != float("inf") else "N/A",
    }])

    st.dataframe(forecast_df, use_container_width=True, hide_index=True)

    st.caption(
        f"Forecast based on combined avg daily consumption (days with usage only). "
        f"End of week = Sunday **{sunday.strftime('%d %b %Y')}** ({days_remaining} day(s) remaining)."
    )

    if proj_pct < 20:
        st.warning(f"Combined tanks projected to be below 20% by end of week ({proj_pct:.1f}%). Consider ordering fuel.")
    elif proj_pct < 40:
        st.info(f"Combined tanks projected to be at {proj_pct:.1f}% by end of week.")

st.divider()

# ── Month-on-month comparison ─────────────────────────────────────────────────
st.subheader("Month-on-Month Daily Usage Comparison (Tank 1)")

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

    cur_all = daily_df[daily_df["Tank"] == "Tank 1"].groupby("Day")["Consumed (L)"].sum().reset_index()
    prv_all = prev_df[prev_df["Tank"] == "Tank 1"].groupby("Day")["Consumed (L)"].sum().reset_index()

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
        xaxis={"title": "Day of Month", "dtick": 1},
        yaxis={"title": f"Litres vs {prev_label}", "tickformat": "+,.0f"},
        height=360,
        margin=dict(t=40, b=20, l=20, r=20),
        showlegend=False,
        hovermode="x",
    )

    direction_all = "more" if avg_delta_all > 0 else "less"
    colour_word_all = "red" if avg_delta_all > 0 else "green"
    st.markdown(
        f"On average :{colour_word_all}[**{abs(avg_delta_all):,.0f} L/day {direction_all}**] "
        f"this month than {prev_label}"
    )
    st.plotly_chart(fig_all, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Avg Daily ({cur_label[:3]})", f"{cur_avg_all:,.0f} L")
    c2.metric(f"Avg Daily ({prev_label[:3]})", f"{prv_avg_all:,.0f} L")
    c3.metric("Avg Daily Change", f"{avg_delta_all:+,.0f} L")
