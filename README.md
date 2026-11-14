# 📦 SupplyChainPulse

> **End-to-end Supply Chain Operations Analytics Platform** — from raw data generation through SQL KPI engineering to an interactive executive dashboard.

---

## 🧩 Business Problem

Modern supply chains suffer from three chronic pain points:

| Pain Point | Impact |
|---|---|
| **Supplier unreliability** | Stockouts, production stoppages, emergency freight costs |
| **Excess or mis-allocated inventory** | Working capital tied up, high holding costs, write-offs |
| **Reactive decision-making** | Problems discovered after customer impact, not before |

**SupplyChainPulse** addresses all three by aggregating warehouse inventory data, supplier shipment records, and SKU-level cost metadata into a single analytics layer — surfacing OTIF performance, reorder alerts, and 30-day demand forecasts in real time.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SupplyChainPulse                         │
├──────────────┬──────────────────┬──────────────────────────────┤
│  Data Layer  │  Analytics Layer │       Presentation Layer      │
│              │                  │                               │
│  data/       │  sql/            │  app.py  (Streamlit)          │
│  ├ warehouses│  kpi_queries.sql │  ├ Executive Summary          │
│  ├ sku_cat.  │  (OTIF, DIO,     │  ├ Inventory Trends           │
│  ├ shipments │   ROP queries)   │  ├ Supplier Analytics         │
│  └ inv_logs  │                  │  ├ Demand Forecast            │
│              │  src/            │  └ Alerts & Reorder           │
│  (CSV / DB)  │  inventory_      │                               │
│              │  optimizer.py    │  Plotly charts + KPI tiles    │
│              │  (Python + ML)   │                               │
└──────────────┴──────────────────┴──────────────────────────────┘
```

**Data flow:**
1. `src/generate_supply_data.py` → produces 4 CSV datasets in `data/`
2. `src/inventory_optimizer.py` → ingests CSVs, computes metrics, runs forecast
3. `sql/kpi_queries.sql` → production-grade SQL for BI / data-warehouse use
4. `app.py` → Streamlit dashboard calls the optimizer and renders Plotly charts

---

## 🛠 Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Data generation** | Python 3.11+, NumPy, Pandas | Synthetic realistic CSV datasets |
| **Analytics engine** | Pandas, scikit-learn (LinearRegression) | Lead-time variance, OTIF, ROP, 30-day forecast |
| **SQL KPIs** | ANSI SQL (CTEs, Window Functions) | OTIF, Inventory Turnover / DIO, Reorder Points |
| **Dashboard** | Streamlit 1.35, Plotly 5 | Interactive multi-page web UI |
| **Data exchange** | openpyxl | Optional Excel export support |

---

## 📁 Project Structure

```
SupplyChainPulse/
├── app.py                          # Streamlit dashboard entry point
├── requirements.txt                # Python dependencies
├── README.md                       # This file
│
├── data/                           # Generated CSV datasets (git-ignored)
│   ├── warehouses.csv
│   ├── sku_catalog.csv
│   ├── supplier_shipments.csv
│   └── daily_inventory_logs.csv
│
├── src/
│   ├── generate_supply_data.py     # Dataset generator (run once)
│   └── inventory_optimizer.py     # Analytics engine (imported by app.py)
│
└── sql/
    └── kpi_queries.sql             # Production SQL KPI queries
```

---

## ⚡ Local Setup — Step by Step

### Prerequisites
- Python 3.10 or higher
- pip

### 1. Clone the repository

```bash
git clone https://github.com/your-org/supplychainpulse.git
cd supplychainpulse
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Generate the datasets

```bash
python src/generate_supply_data.py
```

Expected output:
```
Generating warehouses.csv …
Generating sku_catalog.csv …
Generating supplier_shipments.csv …
Generating daily_inventory_logs.csv …

✓ All 4 datasets written to: .../data
  warehouses.csv           →   5 rows
  sku_catalog.csv          →  50 rows
  supplier_shipments.csv   → 600 rows
  daily_inventory_logs.csv → 18,250 rows
```

### 5. (Optional) Run the optimizer standalone

```bash
python src/inventory_optimizer.py
```

This prints supplier OTIF tables, risk flags, and a demand forecast preview directly to the terminal.

### 6. Launch the Streamlit dashboard

```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

---

## 📊 Dashboard Pages

| Page | What you see |
|---|---|
| **Executive Summary** | OTIF %, total stockouts, inventory turnover, critical alerts — plus OTIF bar chart and stockout area chart |
| **Inventory Trends** | Warehouse-wise stock level line chart, monthly heatmap, incoming shipments bar |
| **Supplier Analytics** | Lead-time variance scatter, delivery variance box plot, risk-tier data table |
| **Demand Forecast** | Historical demand + 30-day linear forecast with 95% confidence band |
| **Alerts & Reorder** | Critical / Warning / OK breakdown, suggested order quantities, full alert table |

### Sidebar Filters
- **Date Range** — restricts inventory log analysis to the selected window
- **Warehouse** — drill down to a single warehouse or view all

---

## 🔢 KPI Definitions

| KPI | Formula | Target |
|---|---|---|
| **OTIF Rate** | Shipments delivered on-time AND ≥ 95% of avg qty ÷ Total shipments | ≥ 95% |
| **Inventory Turnover** | Units consumed ÷ Average stock level | > 4× per year |
| **DIO (Days Inventory Outstanding)** | 365 ÷ Inventory Turnover | < 90 days |
| **Safety Stock** | Z × σ_demand × √(Lead Time)  (Z = 1.65 for 95% SL) | Dynamically computed |
| **Reorder Point (ROP)** | Avg Daily Demand × Avg Lead Time + Safety Stock | Dynamically computed |

---

## 🗄 SQL Queries Overview (`sql/kpi_queries.sql`)

Three production-grade query blocks, each using CTEs and window functions:

1. **OTIF Performance** — `ROW_NUMBER`, `LAG`, rolling 30-day OTIF window per supplier
2. **Inventory Turnover & DIO** — monthly grain with `DATE_TRUNC`, `LAG` for MoM % change, health classification
3. **Dynamic ROP & Safety Stock** — `ROW_NUMBER` for latest stock snapshot, alert severity tiers, suggested order quantities

Dialect: ANSI SQL — tested compatible with **PostgreSQL**, **BigQuery**, **Snowflake**, and **DuckDB**.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-improvement`
3. Commit your changes: `git commit -m "feat: add ABC analysis"`
4. Push and open a Pull Request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">Built with ❤️ by the Supply Chain Analytics Team</p>
