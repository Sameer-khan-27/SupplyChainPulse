# SupplyChainPulse — Power BI Star Schema & DAX Reference

## 1. Star Schema Design

The Power BI model uses a classic **star schema** to maximise query performance and DAX simplicity. All fact tables connect outward to dimension tables through single-direction relationships.

---

### Entity-Relationship Diagram

```
                   ┌───────────────────┐
                   │  dim_date         │
                   │  (Date Table)     │
                   └────────┬──────────┘
                            │  log_date / order_date
              ┌─────────────┼──────────────────┐
              │             │                  │
   ┌──────────▼──────┐  ┌───▼────────────┐  ┌──▼───────────────────────┐
   │ fact_inventory  │  │ fact_shipments │  │ fact_demand_forecast     │
   │ _logs           │  │                │  │                          │
   └──────────┬──────┘  └───┬────────────┘  └──────────────────────────┘
              │             │
              │   ┌─────────┘
              │   │
   ┌──────────▼───▼────┐    ┌───────────────────┐
   │  dim_sku          │    │  dim_supplier     │
   │  (SKU Catalog)    │    │                   │
   └───────────────────┘    └───────────────────┘
              │
   ┌──────────▼────────┐
   │  dim_warehouse    │
   │  (Warehouses)     │
   └───────────────────┘
```

---

## 2. Table Definitions & Relationships

### Dimension Tables

| Table | Key Column | Source File | Notes |
|---|---|---|---|
| `dim_date` | `DateKey` (YYYYMMDD) | Auto-generated | Continuous calendar 2023-01-01 → 2025-12-31 |
| `dim_sku` | `sku_id` | `sku_catalog.csv` | Velocity tier, category, cost |
| `dim_warehouse` | `warehouse_id` | `warehouses.csv` | Region, country, capacity |
| `dim_supplier` | `supplier_name` | Derived from `supplier_shipments.csv` | Distinct supplier list |

### Fact Tables

| Table | Grain | Foreign Keys | Row Count |
|---|---|---|---|
| `fact_inventory_logs` | 1 row per warehouse × SKU × day | `warehouse_id`, `sku_id`, `log_date` → DateKey | ~100K+ |
| `fact_shipments` | 1 row per shipment | `warehouse_id`, `sku_id`, `order_date`, `supplier_name` | ~40K |
| `fact_demand_forecast` | 1 row per SKU × forecast day | `sku_id`, `forecast_date` → DateKey | ~1,500 |

### Relationship Configuration

```
fact_inventory_logs[warehouse_id]   → dim_warehouse[warehouse_id]   (Many:1, Single)
fact_inventory_logs[sku_id]         → dim_sku[sku_id]               (Many:1, Single)
fact_inventory_logs[log_date]       → dim_date[Date]                (Many:1, Single)

fact_shipments[sku_id]              → dim_sku[sku_id]               (Many:1, Single)
fact_shipments[warehouse_id]        → dim_warehouse[warehouse_id]   (Many:1, Single)
fact_shipments[order_date]          → dim_date[Date]                (Many:1, Single)
fact_shipments[supplier_name]       → dim_supplier[supplier_name]   (Many:1, Single)

fact_demand_forecast[sku_id]        → dim_sku[sku_id]               (Many:1, Single)
fact_demand_forecast[forecast_date] → dim_date[Date]                (Many:1, Single)
```

> **Cross-filter direction:** All relationships are **single-direction** (dim → fact). Do NOT use bidirectional unless explicitly required for a specific visual — it causes ambiguous filter propagation.

---

## 3. dim_date — M Query (Power Query)

Paste into a **Blank Query** in Power Query Editor:

```powerquery
let
    StartDate = #date(2023, 1, 1),
    EndDate   = #date(2025, 12, 31),
    DateList  = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1,0,0,0)),
    DateTable = Table.FromList(DateList, Splitter.SplitByNothing(), {"Date"}),
    AddDateKey   = Table.AddColumn(DateTable, "DateKey", each
                       Date.Year([Date])*10000 + Date.Month([Date])*100 + Date.Day([Date]),
                       Int32.Type),
    AddYear      = Table.AddColumn(AddDateKey, "Year", each Date.Year([Date]), Int32.Type),
    AddQuarter   = Table.AddColumn(AddYear, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date]))),
    AddMonth     = Table.AddColumn(AddQuarter, "MonthNum", each Date.Month([Date]), Int32.Type),
    AddMonthName = Table.AddColumn(AddMonth, "MonthName", each Date.MonthName([Date])),
    AddWeek      = Table.AddColumn(AddMonthName, "WeekOfYear", each Date.WeekOfYear([Date]), Int32.Type),
    AddDOW       = Table.AddColumn(AddWeek, "DayOfWeek", each Date.DayOfWeekName([Date])),
    AddYM        = Table.AddColumn(AddDOW, "YearMonth", each Text.From(Date.Year([Date])) & "-"
                       & Text.PadStart(Text.From(Date.Month([Date])), 2, "0")),
    AddYQ        = Table.AddColumn(AddYM, "YearQuarter", each
                       Text.From(Date.Year([Date])) & " Q" & Text.From(Date.QuarterOfYear([Date]))),
    SetDateType  = Table.TransformColumnTypes(AddYQ, {{"Date", type date}})
in
    SetDateType
```

---

## 4. DAX Measures

All measures should be placed in a **dedicated measures table** named `_Measures` (a blank table with no rows).

---

### 4.1 Inventory KPIs

```dax
-- Total Inventory Value (current filter context)
[Total Inventory Value] =
SUM(fact_inventory_logs[inventory_value_usd])

-- Average Daily Inventory Value
[Avg Daily Inventory Value] =
AVERAGEX(
    VALUES(dim_date[Date]),
    CALCULATE(SUM(fact_inventory_logs[inventory_value_usd]))
)

-- YTD Inventory Value
[YTD Inventory Value] =
TOTALYTD(
    SUM(fact_inventory_logs[inventory_value_usd]),
    dim_date[Date]
)

-- Prior Year Inventory Value (same period)
[PY Inventory Value] =
CALCULATE(
    SUM(fact_inventory_logs[inventory_value_usd]),
    SAMEPERIODLASTYEAR(dim_date[Date])
)

-- YoY Inventory Value Change %
[YoY Inventory Value %] =
DIVIDE(
    [YTD Inventory Value] - [PY Inventory Value],
    [PY Inventory Value],
    0
)
```

---

### 4.2 Stockout & Overstock Rates

```dax
-- Stockout Rate % (rolling 30-day)
[Stockout Rate % (30D)] =
VAR Last30Days =
    DATESINPERIOD(
        dim_date[Date],
        LASTDATE(dim_date[Date]),
        -30,
        DAY
    )
RETURN
CALCULATE(
    DIVIDE(
        SUM(fact_inventory_logs[stockout_flag]),
        COUNT(fact_inventory_logs[log_id]),
        0
    ),
    Last30Days
) * 100

-- Stockout Rate % (all-time)
[Stockout Rate % (All)] =
DIVIDE(
    SUM(fact_inventory_logs[stockout_flag]),
    COUNT(fact_inventory_logs[log_id]),
    0
) * 100

-- Overstock Rate %
[Overstock Rate %] =
DIVIDE(
    SUM(fact_inventory_logs[overstock_flag]),
    COUNT(fact_inventory_logs[log_id]),
    0
) * 100

-- Active Stockout SKUs (distinct count on latest date)
[Active Stockout SKUs] =
CALCULATE(
    DISTINCTCOUNT(fact_inventory_logs[sku_id]),
    fact_inventory_logs[stockout_flag] = 1,
    LASTDATE(dim_date[Date])
)
```

---

### 4.3 Supplier OTIF

```dax
-- Overall OTIF Rate %
[OTIF Rate %] =
DIVIDE(
    SUM(fact_shipments[is_otif]),
    COUNTROWS(
        FILTER(fact_shipments, fact_shipments[status] <> "Cancelled")
    ),
    0
) * 100

-- Rolling 90-Day OTIF Rate %
[OTIF Rate % (90D)] =
VAR Last90Days =
    DATESINPERIOD(
        dim_date[Date],
        LASTDATE(dim_date[Date]),
        -90,
        DAY
    )
RETURN
CALCULATE(
    DIVIDE(
        SUM(fact_shipments[is_otif]),
        COUNTROWS(
            FILTER(fact_shipments, fact_shipments[status] <> "Cancelled")
        ),
        0
    ),
    Last90Days
) * 100

-- Average Supplier Lead Time (days)
[Avg Lead Time (Days)] =
CALCULATE(
    AVERAGE(fact_shipments[actual_lead_time_days]),
    fact_shipments[status] IN {"Delivered", "Partial", "Delayed"}
)

-- Lead Time Variance (days above standard)
[Avg Lead Time Variance] =
CALCULATE(
    AVERAGE(fact_shipments[lead_time_variance_days]),
    fact_shipments[status] IN {"Delivered", "Partial", "Delayed"}
)
```

---

### 4.4 Inventory Turnover & DIO

```dax
-- Total COGS (units sold × unit cost)
[Total COGS] =
SUMX(
    fact_inventory_logs,
    fact_inventory_logs[units_sold] * RELATED(dim_sku[unit_cost_usd])
)

-- Inventory Turnover Ratio
[Inventory Turnover Ratio] =
DIVIDE(
    [Total COGS],
    [Avg Daily Inventory Value] * 365,
    0
)

-- Days of Inventory Outstanding (DIO)
[DIO (Days)] =
DIVIDE(
    365,
    [Inventory Turnover Ratio],
    0
)
```

---

### 4.5 Demand Forecast

```dax
-- Total Forecasted Demand (next 30 days)
[Forecasted Demand (30D)] =
CALCULATE(
    SUM(fact_demand_forecast[forecasted_demand]),
    DATESINPERIOD(
        dim_date[Date],
        TODAY(),
        30,
        DAY
    )
)

-- Forecast vs Actual Demand Gap %
[Forecast vs Actual Gap %] =
VAR ActualDemand =
    CALCULATE(
        SUM(fact_inventory_logs[units_demanded]),
        DATESINPERIOD(dim_date[Date], LASTDATE(dim_date[Date]), -30, DAY)
    )
VAR ForecastedDemand =
    CALCULATE(
        SUM(fact_demand_forecast[forecasted_demand]),
        DATESINPERIOD(dim_date[Date], LASTDATE(dim_date[Date]), -30, DAY)
    )
RETURN
DIVIDE(ForecastedDemand - ActualDemand, ActualDemand, 0) * 100
```

---

## 5. Dark-Themed Executive Dashboard Layout

### Theme JSON (Paste into Power BI Desktop > View > Browse for themes)

```json
{
  "name": "SupplyChainPulse Dark",
  "dataColors": ["#3B82F4", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4"],
  "background": "#0F172A",
  "foreground": "#F8FAFC",
  "tableAccent": "#3B82F4",
  "visualStyles": {
    "*": {
      "*": {
        "background": [{"color": {"solid": {"color": "#1E293B"}}}],
        "border": [{"color": {"solid": {"color": "#334155"}}}],
        "fontColor": [{"color": {"solid": {"color": "#F8FAFC"}}}],
        "labelColor": [{"color": {"solid": {"color": "#94A3B8"}}}]
      }
    }
  }
}
```

### Page Layout — 3 Executive Dashboard Pages

**Page 1: Inventory Health Overview**
| Visual | Measure | Position |
|---|---|---|
| KPI Card | `[Stockout Rate % (30D)]` | Top-left |
| KPI Card | `[Overstock Rate %]` | Top-center-left |
| KPI Card | `[Active Stockout SKUs]` | Top-center-right |
| KPI Card | `[YTD Inventory Value]` with `[YoY Inventory Value %]` | Top-right |
| Line Chart | `[Stockout Rate % (30D)]` over `dim_date[Date]` by `dim_warehouse[region]` | Center-left |
| Bar Chart | `[DIO (Days)]` by `dim_sku[category]` | Center-right |
| Matrix | `dim_warehouse` × `dim_sku[velocity_tier]` × `[Total Inventory Value]` | Bottom |

**Page 2: Supplier Performance**
| Visual | Measure | Position |
|---|---|---|
| KPI Card | `[OTIF Rate % (90D)]` | Top-left |
| KPI Card | `[Avg Lead Time (Days)]` | Top-center |
| KPI Card | `[Avg Lead Time Variance]` | Top-right |
| Clustered Bar | `[OTIF Rate %]` by `dim_supplier[supplier_name]` (sorted desc) | Center |
| Line + Column | `[OTIF Rate % (90D)]` (line) + shipment count (bar) over time | Bottom-left |
| Donut | Shipments by `status` | Bottom-right |

**Page 3: Demand Forecast & Reorder Alerts**
| Visual | Measure | Position |
|---|---|---|
| Ribbon Chart | `[Forecasted Demand (30D)]` by `dim_sku[category]` | Top |
| Scatter Plot | `[DIO (Days)]` vs `[Stockout Rate % (All)]` by SKU (bubble = inventory value) | Center-left |
| Table | Top 20 SKUs: `sku_name`, `closing_stock`, `days_of_supply`, `alert_level` from SQL | Center-right |
| Gauge | `[OTIF Rate %]` target: 95% | Bottom-left |
| Bar | `[Forecast vs Actual Gap %]` by SKU | Bottom-right |

---

## 6. Microsoft Fabric Architecture (Optional)

For enterprise deployment on Microsoft Fabric:

```
Raw CSV Files
     │
     ▼
Fabric Lakehouse (Delta Tables)
  ├── Bronze Layer: raw CSVs → Delta via Dataflow Gen2
  ├── Silver Layer: cleaned/joined tables (Spark Notebook)
  └── Gold Layer:  pre-aggregated KPI tables (SQL Analytics Endpoint)
         │
         ▼
Power BI Semantic Model (DirectLake mode)
         │
         ▼
Executive Dashboard (Power BI Report)
         │
         ▼
Fabric Data Activator (automated stockout alerts via email/Teams)
```

**DirectLake Connection**: Point the Power BI semantic model to the Gold layer Delta tables in the Lakehouse using DirectLake mode — eliminates import/refresh scheduling and enables real-time query over live Delta files.
