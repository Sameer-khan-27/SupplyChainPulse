"""
app.py  –  SupplyChainPulse Dashboard
======================================
Interactive Streamlit web dashboard for supply-chain operations analytics.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Allow importing from src/ when running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from inventory_optimizer import run_optimization  # noqa: E402

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SupplyChainPulse",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* Sidebar */
        [data-testid="stSidebar"] { background-color: #0f172a; }
        [data-testid="stSidebar"] * { color: #e2e8f0 !important; }

        /* KPI cards */
        .kpi-card {
            background: #1e293b;
            border-radius: 12px;
            padding: 20px 24px;
            text-align: center;
            border-left: 4px solid #3b82f6;
            margin-bottom: 8px;
        }
        .kpi-value { font-size: 2.2rem; font-weight: 700; color: #f1f5f9; }
        .kpi-label { font-size: 0.85rem; color: #94a3b8; margin-top: 4px; }

        /* Section headers */
        .section-header {
            font-size: 1.1rem;
            font-weight: 600;
            color: #f1f5f9;
            border-bottom: 2px solid #3b82f6;
            padding-bottom: 6px;
            margin: 24px 0 16px;
        }

        /* Alert badges */
        .badge-critical { background:#ef4444; color:#fff; border-radius:6px;
                          padding:2px 10px; font-size:0.78rem; font-weight:600; }
        .badge-warning  { background:#f59e0b; color:#fff; border-radius:6px;
                          padding:2px 10px; font-size:0.78rem; font-weight:600; }
        .badge-ok       { background:#10b981; color:#fff; border-radius:6px;
                          padding:2px 10px; font-size:0.78rem; font-weight:600; }

        /* General dark background */
        .stApp { background-color: #0f172a; color: #f1f5f9; }
        h1,h2,h3,h4,h5,h6,p,li,label,span { color: #f1f5f9 !important; }
        .stDataFrame { background: #1e293b; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Data loading (cached) ──────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading supply-chain data …")
def load_all() -> dict:
    return run_optimization()


data = load_all()

warehouses   = data["warehouses"]
shipments    = data["shipments"]
logs         = data["logs"]
lt_df        = data["lead_time_df"]
forecast_df  = data["forecast_df"]
alert_df     = data["alert_df"]

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📦 SupplyChainPulse")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["Executive Summary", "Inventory Trends", "Supplier Analytics", "Demand Forecast", "Alerts & Reorder"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Date filter
    min_date = logs["Date"].min().date()
    max_date = logs["Date"].max().date()
    date_range = st.date_input(
        "📅 Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date

    # Warehouse filter
    all_wh   = ["All Warehouses"] + warehouses["Warehouse_ID"].tolist()
    selected_wh = st.selectbox("🏭 Warehouse", all_wh)

    st.markdown("---")
    st.caption("SupplyChainPulse v1.0  |  Analytics Lead Dashboard")


# ── Filter logs ────────────────────────────────────────────────────────────────
mask = (logs["Date"].dt.date >= start_date) & (logs["Date"].dt.date <= end_date)
filtered_logs = logs[mask].copy()
if selected_wh != "All Warehouses":
    filtered_logs = filtered_logs[filtered_logs["Warehouse_ID"] == selected_wh]

# ── Helper: dark Plotly template ───────────────────────────────────────────────
DARK_TEMPLATE  = "plotly_dark"
PLOTLY_LAYOUT  = dict(
    template=DARK_TEMPLATE,
    paper_bgcolor="#1e293b",
    plot_bgcolor="#1e293b",
    font=dict(color="#f1f5f9", size=12),
    margin=dict(l=40, r=20, t=40, b=40),
)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Executive Summary
# ══════════════════════════════════════════════════════════════════════════════
if page == "Executive Summary":
    st.markdown("# 📦 SupplyChainPulse — Executive Summary")
    st.markdown(f"**Period:** {start_date}  →  {end_date}  |  **Warehouse:** {selected_wh}")
    st.markdown("---")

    # ── KPI Calculations ──────────────────────────────────────────────────────
    # OTIF
    s = shipments.copy()
    s["is_late"]     = (s["Actual_Delivery_Date"] > s["Promised_Date"]).astype(int)
    supplier_avg_qty = s.groupby("Supplier_Name")["Quantity"].transform("mean")
    s["is_in_full"]  = (s["Quantity"] >= 0.95 * supplier_avg_qty).astype(int)
    s["is_otif"]     = (s["is_late"] == 0) & (s["is_in_full"] == 1)
    otif_rate        = round(s["is_otif"].mean() * 100, 1)

    # Total stockouts in period
    total_stockouts = int(filtered_logs["Stockout_Flag"].sum())

    # Average Inventory Turnover (simple proxy)
    avg_stock  = filtered_logs["Stock_Level"].mean()
    total_recv = filtered_logs["Incoming_Shipment"].sum()
    inv_turnover = round(total_recv / avg_stock, 2) if avg_stock > 0 else 0

    # Critical alerts
    critical_count = int((alert_df["alert"] == "CRITICAL").sum())

    # ── KPI Tiles ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value" style="color:#22c55e">{otif_rate}%</div>'
            f'<div class="kpi-label">Supplier OTIF Rate</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        color = "#ef4444" if total_stockouts > 50 else "#f59e0b" if total_stockouts > 10 else "#22c55e"
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value" style="color:{color}">{total_stockouts:,}</div>'
            f'<div class="kpi-label">Total Stockout Events</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value" style="color:#38bdf8">{inv_turnover}x</div>'
            f'<div class="kpi-label">Avg Inventory Turnover</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c4:
        color = "#ef4444" if critical_count > 0 else "#22c55e"
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value" style="color:{color}">{critical_count}</div>'
            f'<div class="kpi-label">Critical Stock Alerts</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Summary Charts (2-column) ─────────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<div class="section-header">📊 OTIF % by Supplier</div>', unsafe_allow_html=True)
        fig_otif = px.bar(
            lt_df.sort_values("otif_pct"),
            x="otif_pct",
            y="Supplier_Name",
            orientation="h",
            color="risk_tier",
            color_discrete_map={"Healthy": "#22c55e", "Watch": "#f59e0b", "Critical": "#ef4444"},
            labels={"otif_pct": "OTIF %", "Supplier_Name": "", "risk_tier": "Risk"},
            text=lt_df.sort_values("otif_pct")["otif_pct"].apply(lambda x: f"{x:.1f}%"),
        )
        fig_otif.update_traces(textposition="outside")
        fig_otif.update_layout(**PLOTLY_LAYOUT, xaxis_range=[0, 110])
        st.plotly_chart(fig_otif, use_container_width=True)

    with col_b:
        st.markdown('<div class="section-header">📉 Daily Stockout Events</div>', unsafe_allow_html=True)
        daily_so = (
            filtered_logs.groupby("Date")["Stockout_Flag"].sum().reset_index()
        )
        fig_so = px.area(
            daily_so, x="Date", y="Stockout_Flag",
            labels={"Stockout_Flag": "Stockout Events", "Date": ""},
            color_discrete_sequence=["#ef4444"],
        )
        fig_so.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig_so, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Inventory Trends
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Inventory Trends":
    st.markdown("# 📈 Warehouse-Wise Stock Level Trends")
    st.markdown("---")

    # Aggregate: daily average stock across all SKUs per warehouse
    agg = (
        filtered_logs.groupby(["Date", "Warehouse_ID"])["Stock_Level"]
        .mean()
        .reset_index()
    )

    # Line chart
    st.markdown('<div class="section-header">Average Daily Stock Level by Warehouse</div>', unsafe_allow_html=True)
    fig_trend = px.line(
        agg, x="Date", y="Stock_Level",
        color="Warehouse_ID",
        labels={"Stock_Level": "Avg Stock Level (units)", "Date": "", "Warehouse_ID": "Warehouse"},
    )
    fig_trend.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig_trend, use_container_width=True)

    # Heatmap: monthly avg stock per warehouse
    st.markdown('<div class="section-header">Monthly Stock Heatmap (Avg Units)</div>', unsafe_allow_html=True)
    filtered_logs["Month"] = filtered_logs["Date"].dt.to_period("M").astype(str)
    heat_data = (
        filtered_logs.groupby(["Month", "Warehouse_ID"])["Stock_Level"]
        .mean()
        .reset_index()
        .pivot(index="Warehouse_ID", columns="Month", values="Stock_Level")
        .fillna(0)
    )
    fig_heat = go.Figure(
        go.Heatmap(
            z=heat_data.values,
            x=heat_data.columns.tolist(),
            y=heat_data.index.tolist(),
            colorscale="Blues",
            hoverongaps=False,
            colorbar=dict(title="Avg Units"),
        )
    )
    fig_heat.update_layout(**PLOTLY_LAYOUT, xaxis_title="Month", yaxis_title="Warehouse")
    st.plotly_chart(fig_heat, use_container_width=True)

    # Incoming shipments bar
    st.markdown('<div class="section-header">Total Incoming Shipments by Warehouse</div>', unsafe_allow_html=True)
    ship_agg = (
        filtered_logs.groupby("Warehouse_ID")["Incoming_Shipment"]
        .sum()
        .reset_index()
        .sort_values("Incoming_Shipment", ascending=False)
    )
    fig_ship = px.bar(
        ship_agg, x="Warehouse_ID", y="Incoming_Shipment",
        color="Incoming_Shipment",
        color_continuous_scale="Blues",
        labels={"Incoming_Shipment": "Units Received", "Warehouse_ID": "Warehouse"},
        text_auto=True,
    )
    fig_ship.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig_ship, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Supplier Analytics
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Supplier Analytics":
    st.markdown("# 🚚 Supplier Lead-Time Anomaly Detection")
    st.markdown("---")

    # Scatter: avg variance vs late %
    st.markdown('<div class="section-header">Lead-Time Variance vs. Late Delivery Rate</div>', unsafe_allow_html=True)
    fig_scatter = px.scatter(
        lt_df,
        x="avg_variance_days",
        y="late_pct",
        size="total_shipments",
        color="risk_tier",
        color_discrete_map={"Healthy": "#22c55e", "Watch": "#f59e0b", "Critical": "#ef4444"},
        text="Supplier_Name",
        labels={
            "avg_variance_days": "Avg Lead-Time Variance (days)",
            "late_pct":          "Late Delivery Rate (%)",
            "risk_tier":         "Risk Tier",
        },
        size_max=50,
    )
    fig_scatter.update_traces(textposition="top center", textfont_size=11)
    # Annotate quadrant lines
    fig_scatter.add_hline(y=20, line_dash="dot", line_color="#94a3b8", annotation_text="20% late threshold")
    fig_scatter.add_vline(x=3,  line_dash="dot", line_color="#94a3b8", annotation_text="3-day variance")
    fig_scatter.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig_scatter, use_container_width=True)

    # Distribution of delivery variances per supplier (box plot)
    st.markdown('<div class="section-header">Delivery Variance Distribution by Supplier</div>', unsafe_allow_html=True)
    s_copy = shipments.copy()
    s_copy["variance_days"] = (
        s_copy["Actual_Delivery_Date"] - s_copy["Promised_Date"]
    ).dt.days

    fig_box = px.box(
        s_copy,
        x="Supplier_Name",
        y="variance_days",
        color="Supplier_Name",
        points="outliers",
        labels={"variance_days": "Variance (days; negative = early)", "Supplier_Name": ""},
    )
    fig_box.add_hline(y=0, line_dash="dash", line_color="#f1f5f9", annotation_text="On-time")
    fig_box.update_layout(**PLOTLY_LAYOUT, showlegend=False)
    st.plotly_chart(fig_box, use_container_width=True)

    # Data table
    st.markdown('<div class="section-header">Supplier Performance Summary</div>', unsafe_allow_html=True)
    display_lt = lt_df[
        ["Supplier_Name", "total_shipments", "avg_variance_days",
         "std_variance_days", "late_pct", "otif_pct", "risk_tier"]
    ].copy()
    display_lt.columns = [
        "Supplier", "Shipments", "Avg Variance (d)",
        "Std Variance (d)", "Late %", "OTIF %", "Risk Tier",
    ]

    def _color_risk(val: str) -> str:
        return {
            "Critical": "background-color:#7f1d1d; color:#fca5a5",
            "Watch":    "background-color:#78350f; color:#fde68a",
            "Healthy":  "background-color:#14532d; color:#bbf7d0",
        }.get(val, "")

    st.dataframe(
      display_lt.style.map(_color_risk, subset=["Risk Tier"]),
        use_container_width=True,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Demand Forecast
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Demand Forecast":
    st.markdown("# 🔮 30-Day Demand Forecast")
    st.markdown("---")

    # Historical daily demand
    hist_demand = (
        logs.groupby("Date")["Incoming_Shipment"]
        .sum()
        .reset_index()
        .rename(columns={"Incoming_Shipment": "demand"})
    )

    fig_forecast = go.Figure()

    # Historical trace
    fig_forecast.add_trace(go.Scatter(
        x=hist_demand["Date"], y=hist_demand["demand"],
        mode="lines", name="Historical Demand",
        line=dict(color="#38bdf8", width=1.5),
    ))

    # Forecast band
    fig_forecast.add_trace(go.Scatter(
        x=pd.concat([forecast_df["Date"], forecast_df["Date"].iloc[::-1]]),
        y=pd.concat([forecast_df["Upper_95"], forecast_df["Lower_95"].iloc[::-1]]),
        fill="toself",
        fillcolor="rgba(99,102,241,0.15)",
        line=dict(color="rgba(0,0,0,0)"),
        name="95% Confidence Band",
    ))

    # Forecast line
    fig_forecast.add_trace(go.Scatter(
        x=forecast_df["Date"], y=forecast_df["Forecasted_Demand"],
        mode="lines+markers", name="Forecast",
        line=dict(color="#a78bfa", width=2.5, dash="dot"),
        marker=dict(size=5),
    ))

    fig_forecast.update_layout(
        **PLOTLY_LAYOUT,
        xaxis_title="Date",
        yaxis_title="Daily Units Incoming",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    st.plotly_chart(fig_forecast, use_container_width=True)

    st.markdown('<div class="section-header">Forecast Values Table</div>', unsafe_allow_html=True)
    st.dataframe(
        forecast_df.rename(columns={
            "Date": "Forecast Date",
            "Forecasted_Demand": "Demand (units)",
            "Lower_95": "Lower Bound (95%)",
            "Upper_95": "Upper Bound (95%)",
        }),
        use_container_width=True,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — Alerts & Reorder
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Alerts & Reorder":
    st.markdown("# 🚨 Alerts & Reorder Point Analysis")
    st.markdown("---")

    # Summary banner
    n_critical = int((alert_df["alert"] == "CRITICAL").sum())
    n_warning  = int((alert_df["alert"] == "WARNING").sum())
    n_ok       = int((alert_df["alert"] == "OK").sum())

    b1, b2, b3 = st.columns(3)
    with b1:
        st.markdown(
            f'<div class="kpi-card" style="border-left-color:#ef4444">'
            f'<div class="kpi-value" style="color:#ef4444">{n_critical}</div>'
            f'<div class="kpi-label">🚨 Critical Alerts</div></div>',
            unsafe_allow_html=True,
        )
    with b2:
        st.markdown(
            f'<div class="kpi-card" style="border-left-color:#f59e0b">'
            f'<div class="kpi-value" style="color:#f59e0b">{n_warning}</div>'
            f'<div class="kpi-label">⚠️ Warning Alerts</div></div>',
            unsafe_allow_html=True,
        )
    with b3:
        st.markdown(
            f'<div class="kpi-card" style="border-left-color:#22c55e">'
            f'<div class="kpi-value" style="color:#22c55e">{n_ok}</div>'
            f'<div class="kpi-label">✅ OK – Adequate Stock</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Donut chart
    st.markdown('<div class="section-header">Alert Distribution</div>', unsafe_allow_html=True)
    col_d, col_t = st.columns([1, 2])
    with col_d:
        fig_donut = px.pie(
            names=["Critical", "Warning", "OK"],
            values=[n_critical, n_warning, n_ok],
            hole=0.55,
            color=["Critical", "Warning", "OK"],
            color_discrete_map={"Critical": "#ef4444", "Warning": "#f59e0b", "OK": "#22c55e"},
        )
        fig_donut.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_t:
        # Bar: suggested order qty for critical/warning items
        at_risk = alert_df[alert_df["alert"] != "OK"].head(20).copy()
        at_risk["label"] = at_risk["Warehouse_ID"] + " / " + at_risk["SKU_ID"]
        fig_order = px.bar(
            at_risk.sort_values("suggested_order_qty", ascending=False),
            x="suggested_order_qty",
            y="label",
            orientation="h",
            color="alert",
            color_discrete_map={"CRITICAL": "#ef4444", "WARNING": "#f59e0b"},
            labels={"suggested_order_qty": "Suggested Order Qty", "label": "", "alert": "Alert"},
        )
        fig_order.update_layout(**PLOTLY_LAYOUT, yaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(fig_order, use_container_width=True)

    # Full alerts table
    st.markdown('<div class="section-header">Full Alert Table</div>', unsafe_allow_html=True)

    display_alerts = alert_df[
        ["Warehouse_ID", "SKU_ID", "current_stock", "safety_stock",
         "reorder_point", "suggested_order_qty", "alert"]
    ].copy()
    display_alerts.columns = [
        "Warehouse", "SKU", "Current Stock", "Safety Stock",
        "Reorder Point", "Suggested Order Qty", "Alert",
    ]
    display_alerts["Current Stock"]     = display_alerts["Current Stock"].round(0).astype(int)
    display_alerts["Safety Stock"]      = display_alerts["Safety Stock"].round(0).astype(int)
    display_alerts["Reorder Point"]     = display_alerts["Reorder Point"].round(0).astype(int)
    display_alerts["Suggested Order Qty"] = display_alerts["Suggested Order Qty"].round(0).astype(int)

    def _color_alert(val: str) -> str:
        return {
            "CRITICAL": "background-color:#7f1d1d; color:#fca5a5",
            "WARNING":  "background-color:#78350f; color:#fde68a",
            "OK":       "background-color:#14532d; color:#bbf7d0",
        }.get(val, "")

    st.dataframe(
        display_alerts.style.map(_color_alert, subset=["Alert"]),
        use_container_width=True,
        hide_index=True,
    )


# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="text-align:center; font-size:0.78rem; color:#475569;">'
    "SupplyChainPulse  |  Built with Streamlit & Plotly  |  Data Analytics Lead Dashboard"
    "</p>",
    unsafe_allow_html=True,
)
