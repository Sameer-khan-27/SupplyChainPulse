"""
generate_supply_data.py
-----------------------
Generates realistic synthetic supply chain CSV datasets and writes them to the
data/ directory at the project root. Run once before launching the dashboard.

Usage:
    python src/generate_supply_data.py
"""

import os
import random
from pathlib import Path

import numpy as np
import pandas as pd

# ── Reproducibility ────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ── Output directories ─────────────────────────────────────────────────────────
# Primary output: data/ (read by the dashboard and optimizer)
# Mirror output:  data/raw/ (canonical raw-data landing zone)
DATA_DIR     = Path(__file__).resolve().parent.parent / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 1. Warehouses ──────────────────────────────────────────────────────────────
def generate_warehouses() -> pd.DataFrame:
    warehouses = [
        {"Warehouse_ID": "WH-001", "Location": "Chicago, IL",    "Capacity": 50_000},
        {"Warehouse_ID": "WH-002", "Location": "Dallas, TX",     "Capacity": 75_000},
        {"Warehouse_ID": "WH-003", "Location": "Atlanta, GA",    "Capacity": 40_000},
        {"Warehouse_ID": "WH-004", "Location": "Los Angeles, CA","Capacity": 90_000},
        {"Warehouse_ID": "WH-005", "Location": "Seattle, WA",    "Capacity": 35_000},
    ]
    return pd.DataFrame(warehouses)


# ── 2. SKU Catalogue ───────────────────────────────────────────────────────────
def generate_sku_catalog() -> pd.DataFrame:
    categories = ["Electronics", "Apparel", "Grocery", "Hardware", "Pharma"]
    skus = []
    for i in range(1, 51):
        cat = categories[(i - 1) % len(categories)]
        unit_cost = round(random.uniform(5.0, 500.0), 2)
        holding_cost = round(unit_cost * random.uniform(0.18, 0.28), 2)
        skus.append({
            "SKU_ID":       f"SKU-{i:04d}",
            "Category":     cat,
            "Unit_Cost":    unit_cost,
            "Holding_Cost": holding_cost,
        })
    return pd.DataFrame(skus)


# ── 3. Supplier Shipments ──────────────────────────────────────────────────────
def generate_supplier_shipments(sku_ids: list[str]) -> pd.DataFrame:
    suppliers = [
        "GlobalTech Supply",
        "FastFreight Co.",
        "AsiaPac Logistics",
        "MidWest Distributors",
        "PrimeSource Ltd.",
        "EuroGoods GmbH",
    ]
    records = []
    base_date = pd.Timestamp("2024-01-01")
    for i in range(1, 601):
        promised_offset = random.randint(5, 20)
        # ~20 % of shipments are late; ~5 % are very late (anomalies)
        rand = random.random()
        if rand < 0.05:
            actual_offset = promised_offset + random.randint(10, 30)
        elif rand < 0.20:
            actual_offset = promised_offset + random.randint(1, 9)
        else:
            actual_offset = promised_offset + random.randint(-2, 0)

        order_date    = base_date + pd.Timedelta(days=random.randint(0, 364))
        promised_date = order_date + pd.Timedelta(days=promised_offset)
        actual_date   = order_date + pd.Timedelta(days=max(1, actual_offset))

        records.append({
            "Shipment_ID":          f"SHP-{i:05d}",
            "SKU_ID":               random.choice(sku_ids),
            "Supplier_Name":        random.choice(suppliers),
            "Promised_Date":        promised_date.date(),
            "Actual_Delivery_Date": actual_date.date(),
            "Quantity":             random.randint(50, 2_000),
        })
    return pd.DataFrame(records)


# ── 4. Daily Inventory Logs ────────────────────────────────────────────────────
def generate_daily_inventory_logs(
    warehouse_ids: list[str],
    sku_ids: list[str],
) -> pd.DataFrame:
    date_range = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    # Use a sample of 10 SKUs × 5 warehouses for tractable volume
    sampled_skus = random.sample(sku_ids, 10)
    records = []
    stock_state: dict[tuple, int] = {}

    for date in date_range:
        for wh in warehouse_ids:
            for sku in sampled_skus:
                key = (wh, sku)
                prev_stock = stock_state.get(key, random.randint(200, 1_000))
                incoming   = random.randint(0, 300) if random.random() < 0.3 else 0
                demand     = random.randint(10, 150)
                new_stock  = max(0, prev_stock + incoming - demand)
                stockout   = 1 if new_stock == 0 else 0
                stock_state[key] = new_stock

                records.append({
                    "Date":              date.date(),
                    "Warehouse_ID":      wh,
                    "SKU_ID":            sku,
                    "Stock_Level":       new_stock,
                    "Incoming_Shipment": incoming,
                    "Stockout_Flag":     stockout,
                })
    return pd.DataFrame(records)


# ── Main ───────────────────────────────────────────────────────────────────────
def _write(df: pd.DataFrame, filename: str) -> None:
    """Write df to both data/ and data/raw/ atomically."""
    df.to_csv(DATA_DIR     / filename, index=False)
    df.to_csv(RAW_DATA_DIR / filename, index=False)


def main() -> None:
    print("Generating warehouses.csv …")
    wh_df = generate_warehouses()
    _write(wh_df, "warehouses.csv")

    print("Generating sku_catalog.csv …")
    sku_df = generate_sku_catalog()
    _write(sku_df, "sku_catalog.csv")

    print("Generating supplier_shipments.csv …")
    ship_df = generate_supplier_shipments(sku_df["SKU_ID"].tolist())
    _write(ship_df, "supplier_shipments.csv")

    print("Generating daily_inventory_logs.csv …")
    log_df = generate_daily_inventory_logs(
        wh_df["Warehouse_ID"].tolist(),
        sku_df["SKU_ID"].tolist(),
    )
    _write(log_df, "daily_inventory_logs.csv")

    print(f"\n✓ All 4 datasets written to:")
    print(f"    {DATA_DIR}")
    print(f"    {RAW_DATA_DIR}")
    print(f"  warehouses.csv           → {len(wh_df):,} rows")
    print(f"  sku_catalog.csv          → {len(sku_df):,} rows")
    print(f"  supplier_shipments.csv   → {len(ship_df):,} rows")
    print(f"  daily_inventory_logs.csv → {len(log_df):,} rows")


if __name__ == "__main__":
    main()
