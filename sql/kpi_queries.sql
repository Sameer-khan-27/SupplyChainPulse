-- =============================================================================
-- SupplyChainPulse  |  KPI Queries
-- =============================================================================
-- Dialect : ANSI SQL (compatible with PostgreSQL, BigQuery, Snowflake, DuckDB)
-- Author  : Supply Chain Analytics Team
-- Updated : 2024
-- =============================================================================


-- =============================================================================
-- 1. SUPPLIER ON-TIME IN-FULL (OTIF) PERFORMANCE
-- =============================================================================
-- OTIF = shipments delivered on-time AND in full quantity ÷ total shipments
-- "On-time" means Actual_Delivery_Date <= Promised_Date
-- "In-full" is approximated here as Quantity >= 95 % of average order quantity
-- per supplier (a common industry threshold).
-- =============================================================================

WITH supplier_avg_qty AS (
    -- Baseline expected quantity per supplier
    SELECT
        Supplier_Name,
        AVG(Quantity)   AS avg_qty,
        COUNT(*)        AS total_shipments
    FROM supplier_shipments
    GROUP BY Supplier_Name
),

shipment_flags AS (
    SELECT
        s.Shipment_ID,
        s.Supplier_Name,
        s.Promised_Date,
        s.Actual_Delivery_Date,
        s.Quantity,
        a.avg_qty,
        -- On-time flag
        CASE
            WHEN s.Actual_Delivery_Date <= s.Promised_Date THEN 1 ELSE 0
        END AS is_on_time,
        -- In-full flag  (quantity >= 95 % of supplier average)
        CASE
            WHEN s.Quantity >= 0.95 * a.avg_qty THEN 1 ELSE 0
        END AS is_in_full,
        -- Lead time in days (actual)
        CAST(s.Actual_Delivery_Date AS DATE) - CAST(s.Promised_Date AS DATE)
            + DATEDIFF('day', s.Promised_Date, s.Actual_Delivery_Date)   -- BigQuery / DuckDB
            AS lead_time_variance_days
    FROM supplier_shipments s
    JOIN supplier_avg_qty   a USING (Supplier_Name)
),

otif_per_supplier AS (
    SELECT
        Supplier_Name,
        COUNT(*)                                                    AS total_shipments,
        SUM(is_on_time)                                             AS on_time_count,
        SUM(is_in_full)                                             AS in_full_count,
        SUM(is_on_time * is_in_full)                                AS otif_count,
        ROUND(100.0 * SUM(is_on_time * is_in_full) / COUNT(*), 2)  AS otif_pct,
        ROUND(AVG(lead_time_variance_days), 1)                      AS avg_lead_time_variance_days,
        -- Rolling 30-day OTIF using a window function
        ROUND(
            100.0 * SUM(is_on_time * is_in_full)
                OVER (PARTITION BY Supplier_Name
                      ORDER BY Promised_Date
                      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
            / 30.0,
        2) AS rolling_30d_otif_pct
    FROM shipment_flags
    GROUP BY Supplier_Name
)

SELECT
    Supplier_Name,
    total_shipments,
    otif_count,
    otif_pct                   AS "OTIF %",
    avg_lead_time_variance_days AS "Avg Lead Time Variance (days)",
    -- Risk tier
    CASE
        WHEN otif_pct >= 95  THEN 'Green  – High Performer'
        WHEN otif_pct >= 80  THEN 'Amber  – Watch List'
        ELSE                      'Red    – Critical Risk'
    END AS supplier_risk_tier
FROM otif_per_supplier
ORDER BY otif_pct ASC;


-- =============================================================================
-- 2. INVENTORY TURNOVER RATIO & DAYS OF INVENTORY OUTSTANDING (DIO)
-- =============================================================================
-- Inventory Turnover = Total Units Consumed / Average Stock Level
-- DIO (Days on Hand)  = 365 / Inventory Turnover
-- Computed at Warehouse × SKU grain with a MoM comparison via LAG().
-- =============================================================================

WITH monthly_stats AS (
    SELECT
        DATE_TRUNC('month', Date)        AS month_start,
        Warehouse_ID,
        SKU_ID,
        -- Proxy for COGS: units consumed = closing stock delta + incoming shipments
        SUM(Incoming_Shipment)           AS total_received,
        AVG(Stock_Level)                 AS avg_stock_level,
        SUM(Incoming_Shipment)
            - (MAX(Stock_Level) - MIN(Stock_Level)) AS estimated_units_consumed,
        SUM(Stockout_Flag)               AS stockout_days
    FROM daily_inventory_logs
    GROUP BY DATE_TRUNC('month', Date), Warehouse_ID, SKU_ID
),

turnover_calc AS (
    SELECT
        month_start,
        Warehouse_ID,
        SKU_ID,
        total_received,
        avg_stock_level,
        GREATEST(estimated_units_consumed, 0)   AS units_consumed,
        CASE
            WHEN avg_stock_level > 0
            THEN ROUND(GREATEST(estimated_units_consumed, 0) / avg_stock_level, 3)
            ELSE NULL
        END AS inventory_turnover,
        stockout_days,
        -- Month-over-month change in average stock (LAG window function)
        LAG(avg_stock_level)
            OVER (PARTITION BY Warehouse_ID, SKU_ID
                  ORDER BY month_start)       AS prev_month_avg_stock,
        ROW_NUMBER()
            OVER (PARTITION BY Warehouse_ID, SKU_ID
                  ORDER BY month_start DESC)  AS recency_rank
    FROM monthly_stats
),

dio_calc AS (
    SELECT
        *,
        CASE
            WHEN inventory_turnover > 0
            THEN ROUND(365.0 / inventory_turnover, 1)
            ELSE NULL
        END AS days_inventory_outstanding,
        ROUND(
            100.0 * (avg_stock_level - prev_month_avg_stock) / NULLIF(prev_month_avg_stock, 0),
        1) AS mom_stock_change_pct
    FROM turnover_calc
)

SELECT
    month_start                AS "Month",
    Warehouse_ID,
    SKU_ID,
    ROUND(avg_stock_level, 0)  AS "Avg Stock Level",
    units_consumed             AS "Units Consumed",
    inventory_turnover         AS "Turnover Ratio",
    days_inventory_outstanding AS "DIO (days)",
    stockout_days              AS "Stockout Days",
    mom_stock_change_pct       AS "MoM Stock Δ%",
    -- Classify inventory health
    CASE
        WHEN days_inventory_outstanding > 90  THEN 'Overstocked'
        WHEN days_inventory_outstanding < 15  THEN 'Under-stocked / High Risk'
        ELSE                                       'Healthy'
    END AS inventory_health
FROM dio_calc
WHERE recency_rank = 1          -- Latest month per Warehouse × SKU
ORDER BY days_inventory_outstanding DESC NULLS LAST;


-- =============================================================================
-- 3. DYNAMIC REORDER POINTS (ROP) & SAFETY STOCK ALERTS
-- =============================================================================
-- ROP = (Average Daily Demand × Lead Time) + Safety Stock
-- Safety Stock = Z × σ_demand × √(Lead Time)
-- Z = 1.65 (95 % service level)
-- Lead time is sourced from supplier_shipments; demand from daily_inventory_logs.
-- =============================================================================

WITH daily_demand AS (
    -- Estimate daily demand = Incoming_Shipment - ΔStock  (bounded at 0)
    SELECT
        Warehouse_ID,
        SKU_ID,
        Date,
        GREATEST(
            Incoming_Shipment
                - (Stock_Level - LAG(Stock_Level)
                                   OVER (PARTITION BY Warehouse_ID, SKU_ID
                                         ORDER BY Date)),
        0) AS daily_demand_units
    FROM daily_inventory_logs
),

demand_stats AS (
    SELECT
        Warehouse_ID,
        SKU_ID,
        ROUND(AVG(daily_demand_units), 2)  AS avg_daily_demand,
        ROUND(STDDEV(daily_demand_units), 2) AS stddev_daily_demand,
        COUNT(DISTINCT Date)               AS observation_days
    FROM daily_demand
    GROUP BY Warehouse_ID, SKU_ID
),

supplier_lead_times AS (
    SELECT
        SKU_ID,
        ROUND(AVG(
            DATEDIFF('day', Promised_Date, Actual_Delivery_Date)
        ), 1)                                  AS avg_lead_time_days,
        ROUND(STDDEV(
            DATEDIFF('day', Promised_Date, Actual_Delivery_Date)
        ), 1)                                  AS stddev_lead_time_days
    FROM supplier_shipments
    GROUP BY SKU_ID
),

rop_calc AS (
    SELECT
        d.Warehouse_ID,
        d.SKU_ID,
        d.avg_daily_demand,
        d.stddev_daily_demand,
        l.avg_lead_time_days,
        l.stddev_lead_time_days,
        -- Safety Stock: Z=1.65 for 95% service level
        ROUND(
            1.65 * d.stddev_daily_demand * SQRT(l.avg_lead_time_days),
        0) AS safety_stock_units,
        -- Reorder Point
        ROUND(
            d.avg_daily_demand * l.avg_lead_time_days
            + 1.65 * d.stddev_daily_demand * SQRT(l.avg_lead_time_days),
        0) AS reorder_point_units
    FROM demand_stats d
    JOIN supplier_lead_times l USING (SKU_ID)
),

current_stock AS (
    -- Most recent stock level per Warehouse × SKU
    SELECT
        Warehouse_ID,
        SKU_ID,
        Stock_Level AS current_stock_level
    FROM (
        SELECT
            Warehouse_ID,
            SKU_ID,
            Stock_Level,
            ROW_NUMBER() OVER (
                PARTITION BY Warehouse_ID, SKU_ID
                ORDER BY Date DESC
            ) AS rn
        FROM daily_inventory_logs
    ) ranked
    WHERE rn = 1
)

SELECT
    r.Warehouse_ID,
    r.SKU_ID,
    r.avg_daily_demand          AS "Avg Daily Demand",
    r.avg_lead_time_days        AS "Avg Lead Time (days)",
    r.safety_stock_units        AS "Safety Stock",
    r.reorder_point_units       AS "Reorder Point",
    c.current_stock_level       AS "Current Stock",
    -- Alert flag
    CASE
        WHEN c.current_stock_level <= r.safety_stock_units    THEN '🚨 CRITICAL – Below Safety Stock'
        WHEN c.current_stock_level <= r.reorder_point_units   THEN '⚠️  WARNING  – Below Reorder Point'
        ELSE                                                       '✅ OK       – Adequate Stock'
    END AS stock_alert,
    -- Units to order to bring back to 2× ROP (suggested order quantity)
    GREATEST(
        2 * r.reorder_point_units - c.current_stock_level,
    0) AS suggested_order_qty
FROM rop_calc r
JOIN current_stock c USING (Warehouse_ID, SKU_ID)
ORDER BY
    CASE
        WHEN c.current_stock_level <= r.safety_stock_units  THEN 1
        WHEN c.current_stock_level <= r.reorder_point_units THEN 2
        ELSE 3
    END,
    r.Warehouse_ID,
    r.SKU_ID;
