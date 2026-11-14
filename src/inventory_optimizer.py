"""
inventory_optimizer.py
----------------------
Ingests the generated CSV datasets and produces:
  1. Lead-time variance analysis per supplier.
  2. High-risk supplier flagging (OTIF < 80 %).
  3. A 30-day demand forecast using pure NumPy least-squares (no scipy/sklearn).

Outputs a summary dict and a forecast DataFrame that app.py imports.

Usage (standalone):
    python src/inventory_optimizer.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


# ── Data loaders ───────────────────────────────────────────────────────────────
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (warehouses, skus, shipments, inventory_logs) DataFrames."""
    warehouses = pd.read_csv(DATA_DIR / "warehouses.csv")
    skus       = pd.read_csv(DATA_DIR / "sku_catalog.csv")
    shipments  = pd.read_csv(
        DATA_DIR / "supplier_shipments.csv",
        parse_dates=["Promised_Date", "Actual_Delivery_Date"],
    )
    logs = pd.read_csv(
        DATA_DIR / "daily_inventory_logs.csv",
        parse_dates=["Date"],
    )
    return warehouses, skus, shipments, logs


# ── 1. Lead-time variance ──────────────────────────────────────────────────────
def compute_lead_time_variance(shipments: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with per-supplier lead-time statistics.

    Columns:
        Supplier_Name, total_shipments, avg_promised_lt, avg_actual_lt,
        avg_variance_days, std_variance_days, late_pct, otif_pct,
        risk_tier
    """
    df = shipments.copy()
    df["promised_lt"] = (df["Actual_Delivery_Date"] - df["Promised_Date"]).dt.days
    df["is_late"]     = (df["promised_lt"] > 0).astype(int)

    # OTIF: on-time AND qty >= 95 % of supplier mean
    supplier_avg = df.groupby("Supplier_Name")["Quantity"].transform("mean")
    df["is_in_full"] = (df["Quantity"] >= 0.95 * supplier_avg).astype(int)
    df["is_otif"]    = df["is_late"].eq(0) & df["is_in_full"].eq(1)

    agg = (
        df.groupby("Supplier_Name")
        .agg(
            total_shipments   =("Shipment_ID", "count"),
            avg_variance_days =("promised_lt", "mean"),
            std_variance_days =("promised_lt", "std"),
            late_count        =("is_late",     "sum"),
            otif_count        =("is_otif",     "sum"),
        )
        .reset_index()
    )

    agg["late_pct"] = (agg["late_count"] / agg["total_shipments"] * 100).round(1)
    agg["otif_pct"] = (agg["otif_count"] / agg["total_shipments"] * 100).round(1)
    agg["avg_variance_days"] = agg["avg_variance_days"].round(2)
    agg["std_variance_days"] = agg["std_variance_days"].round(2)

    agg["risk_tier"] = agg["otif_pct"].apply(
        lambda x: "Critical" if x < 80 else ("Watch" if x < 95 else "Healthy")
    )
    return agg.sort_values("otif_pct")


# ── 2. High-risk supplier flags ────────────────────────────────────────────────
def flag_high_risk_suppliers(lt_df: pd.DataFrame) -> pd.DataFrame:
    """Return only suppliers classified as Critical risk (OTIF < 80 %)."""
    return lt_df[lt_df["risk_tier"] == "Critical"].reset_index(drop=True)


# ── 3. 30-day demand forecast ──────────────────────────────────────────────────
def forecast_demand(
    logs: pd.DataFrame,
    horizon_days: int = 30,
) -> pd.DataFrame:
    """
    Fits a simple linear trend model on aggregate daily stock consumption
    and returns a forecast DataFrame for the next `horizon_days` days.

    Demand proxy = sum of Incoming_Shipment across all warehouses/SKUs per day
    (a reasonable proxy for daily fulfilment activity).

    Returns columns: Date, Forecasted_Demand, Lower_95, Upper_95
    """
    daily = (
        logs.groupby("Date")["Incoming_Shipment"]
        .sum()
        .reset_index()
        .rename(columns={"Incoming_Shipment": "demand"})
        .sort_values("Date")
    )

    # Encode date as integer ordinal for regression
    daily["t"] = (daily["Date"] - daily["Date"].min()).dt.days
    X = daily[["t"]].values
    y = daily["demand"].values

    # Fit linear trend via NumPy least-squares: [t, 1] @ [slope, intercept] = y
    t_flat  = daily["t"].values.astype(float)
    A       = np.column_stack([t_flat, np.ones_like(t_flat)])
    coeffs, _, _, _ = np.linalg.lstsq(A, y.astype(float), rcond=None)
    slope, intercept = coeffs

    # Residual std for prediction interval
    y_pred_train = A @ coeffs
    residuals    = y - y_pred_train
    sigma        = residuals.std()
    z95          = 1.96

    # Forecast horizon
    last_t       = int(daily["t"].max())
    last_date    = daily["Date"].max()
    future_t     = np.arange(last_t + 1, last_t + 1 + horizon_days, dtype=float)
    future_dates = pd.date_range(
        start=last_date + pd.Timedelta(days=1),
        periods=horizon_days,
        freq="D",
    )

    y_forecast = slope * future_t + intercept

    forecast_df = pd.DataFrame({
        "Date":               future_dates,
        "Forecasted_Demand":  np.round(y_forecast).astype(int),
        "Lower_95":           np.round(y_forecast - z95 * sigma).astype(int),
        "Upper_95":           np.round(y_forecast + z95 * sigma).astype(int),
    })
    # Clip negatives
    forecast_df["Lower_95"] = forecast_df["Lower_95"].clip(lower=0)
    return forecast_df


# ── 4. Reorder-point alerts ────────────────────────────────────────────────────
def compute_reorder_alerts(
    logs: pd.DataFrame,
    shipments: pd.DataFrame,
    service_level_z: float = 1.65,
) -> pd.DataFrame:
    """
    Compute ROP and safety stock for each Warehouse × SKU and compare
    against the most recent stock level to surface actionable alerts.
    """
    # Daily demand estimate
    daily_demand = (
        logs.groupby(["Warehouse_ID", "SKU_ID"])["Incoming_Shipment"]
        .agg(avg_daily_demand="mean", std_daily_demand="std")
        .reset_index()
    )

    # Lead time stats per SKU
    shipments["lt_days"] = (
        shipments["Actual_Delivery_Date"] - shipments["Promised_Date"]
    ).dt.days.abs()
    lead_times = (
        shipments.groupby("SKU_ID")["lt_days"]
        .agg(avg_lt="mean", std_lt="std")
        .reset_index()
    )

    merged = daily_demand.merge(lead_times, on="SKU_ID", how="left")
    merged["avg_lt"]           = merged["avg_lt"].fillna(7)
    merged["std_lt"]           = merged["std_lt"].fillna(2)
    merged["std_daily_demand"] = merged["std_daily_demand"].fillna(0)

    merged["safety_stock"] = (
        service_level_z * merged["std_daily_demand"] * np.sqrt(merged["avg_lt"])
    ).round(0)
    merged["reorder_point"] = (
        merged["avg_daily_demand"] * merged["avg_lt"] + merged["safety_stock"]
    ).round(0)

    # Latest stock per Warehouse × SKU
    latest_stock = (
        logs.sort_values("Date")
        .groupby(["Warehouse_ID", "SKU_ID"])["Stock_Level"]
        .last()
        .reset_index()
        .rename(columns={"Stock_Level": "current_stock"})
    )

    alerts = merged.merge(latest_stock, on=["Warehouse_ID", "SKU_ID"], how="left")
    alerts["alert"] = alerts.apply(
        lambda r: "CRITICAL"
        if r["current_stock"] <= r["safety_stock"]
        else ("WARNING" if r["current_stock"] <= r["reorder_point"] else "OK"),
        axis=1,
    )
    alerts["suggested_order_qty"] = (
        (2 * alerts["reorder_point"] - alerts["current_stock"]).clip(lower=0).round(0)
    )
    return alerts.sort_values(
        ["alert", "current_stock"],
        key=lambda s: s.map({"CRITICAL": 0, "WARNING": 1, "OK": 2}) if s.name == "alert" else s,
    ).reset_index(drop=True)


# ── Public API used by app.py ──────────────────────────────────────────────────
def run_optimization() -> dict:
    """
    Load data, run all analyses, and return a results dictionary.

    Keys:
        warehouses, skus, shipments, logs,
        lead_time_df, high_risk_df, forecast_df, alert_df
    """
    warehouses, skus, shipments, logs = load_data()
    lt_df       = compute_lead_time_variance(shipments)
    high_risk   = flag_high_risk_suppliers(lt_df)
    forecast_df = forecast_demand(logs)
    alert_df    = compute_reorder_alerts(logs, shipments)

    return {
        "warehouses":    warehouses,
        "skus":          skus,
        "shipments":     shipments,
        "logs":          logs,
        "lead_time_df":  lt_df,
        "high_risk_df":  high_risk,
        "forecast_df":   forecast_df,
        "alert_df":      alert_df,
    }


# ── Standalone execution ───────────────────────────────────────────────────────
if __name__ == "__main__":
    results = run_optimization()

    print("\n── Lead-Time Variance by Supplier ────────────────────────────────")
    print(
        results["lead_time_df"][
            ["Supplier_Name", "total_shipments", "avg_variance_days", "otif_pct", "risk_tier"]
        ].to_string(index=False)
    )

    print("\n── High-Risk Suppliers (OTIF < 80 %) ─────────────────────────────")
    if results["high_risk_df"].empty:
        print("  None — all suppliers meeting 80 %+ OTIF threshold.")
    else:
        print(results["high_risk_df"][["Supplier_Name", "otif_pct", "risk_tier"]].to_string(index=False))

    print("\n── 30-Day Demand Forecast (first 5 rows) ──────────────────────────")
    print(results["forecast_df"].head().to_string(index=False))

    print("\n── Reorder Alerts (top 10) ────────────────────────────────────────")
    print(
        results["alert_df"]
        .head(10)[["Warehouse_ID", "SKU_ID", "current_stock", "reorder_point", "alert"]]
        .to_string(index=False)
    )
