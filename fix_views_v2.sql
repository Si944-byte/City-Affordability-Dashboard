-- ============================================================
-- Fix: Rewrite views to use latest-available data per source
-- Problem: Exact date joins fail because sources have different
--          end dates (rent=Mar 2026, income=2024, labor=Dec 2025)
-- Fix: Each source joins on its own latest available date
-- ============================================================

USE CityAffordability;
GO

-- ============================================================
-- Drop all dependent views first
-- ============================================================
IF OBJECT_ID('prod.vw_latest_snapshot', 'V')       IS NOT NULL DROP VIEW prod.vw_latest_snapshot;
IF OBJECT_ID('prod.vw_city_classification', 'V')   IS NOT NULL DROP VIEW prod.vw_city_classification;
IF OBJECT_ID('prod.vw_affordability_metrics', 'V') IS NOT NULL DROP VIEW prod.vw_affordability_metrics;
GO

-- ============================================================
-- Rebuild vw_affordability_metrics
-- Each fact table joins on its own latest available date per city
-- ============================================================
CREATE VIEW prod.vw_affordability_metrics AS

WITH

-- Latest rent per city per month (primary time spine)
rent AS (
    SELECT
        r.geo_id,
        d.full_date,
        d.year,
        d.quarter,
        d.month,
        d.month_name,
        r.monthly_rent,
        r.annual_rent,
        r.bedroom_type
    FROM prod.fact_rent r
    JOIN prod.dim_date d ON r.date_id = d.date_id
),

-- Latest income per city (most recent ACS year available)
income_latest AS (
    SELECT
        geo_id,
        survey_year,
        median_household_income,
        per_capita_income,
        population,
        ROW_NUMBER() OVER (PARTITION BY geo_id ORDER BY survey_year DESC) AS rn
    FROM prod.fact_income
),

-- Latest labor per city per month
labor AS (
    SELECT
        l.geo_id,
        d.year,
        d.month,
        l.unemployment_rate,
        l.employment_level
    FROM prod.fact_labor l
    JOIN prod.dim_date d ON l.date_id = d.date_id
),

-- Latest home price per city per month
home_prices AS (
    SELECT
        hp.geo_id,
        d.year,
        d.month,
        hp.median_home_price,
        hp.home_type
    FROM prod.fact_home_prices hp
    JOIN prod.dim_date d ON hp.date_id = d.date_id
),

-- Latest mortgage rate per month
mortgage AS (
    SELECT
        d.year,
        d.month,
        m.rate_30yr_fixed
    FROM prod.fact_mortgage_rates m
    JOIN prod.dim_date d ON m.date_id = d.date_id
),

-- Latest available mortgage rate (for months beyond mortgage data)
mortgage_latest AS (
    SELECT TOP 1 rate_30yr_fixed
    FROM prod.fact_mortgage_rates m
    JOIN prod.dim_date d ON m.date_id = d.date_id
    ORDER BY d.full_date DESC
)

SELECT
    g.geo_id,
    g.city_display,
    g.metro_name,
    g.state_abbr,
    g.region,
    g.latitude,
    g.longitude,

    -- Date from rent spine
    r.full_date,
    r.year,
    r.quarter,
    r.month,
    r.month_name,

    -- Rent
    r.monthly_rent,
    r.annual_rent,
    r.bedroom_type,

    -- Income: use latest available ACS year
    i.median_household_income,
    i.per_capita_income,
    i.population,
    i.survey_year AS income_year,

    -- Labor: match on year+month, fall back to latest available
    COALESCE(
        lm.unemployment_rate,
        lb.unemployment_rate
    ) AS unemployment_rate,
    COALESCE(
        lm.employment_level,
        lb.employment_level
    ) AS employment_level,

    -- Home prices: match on year+month, fall back to latest available
    COALESCE(
        hpm.median_home_price,
        hpl.median_home_price
    ) AS median_home_price,

    -- Mortgage: match on year+month, fall back to latest available
    COALESCE(
        mo.rate_30yr_fixed,
        ml.rate_30yr_fixed
    ) AS rate_30yr_fixed,

    -- -------------------------------------------------------
    -- COMPUTED AFFORDABILITY METRICS
    -- -------------------------------------------------------

    -- Rent-to-Income Ratio
    CASE
        WHEN i.median_household_income > 0
        THEN ROUND(r.annual_rent / i.median_household_income, 4)
        ELSE NULL
    END AS rent_to_income_ratio,

    -- Affordable monthly rent (30% threshold)
    ROUND(i.median_household_income * 0.30 / 12, 2) AS affordable_monthly_rent,

    -- Monthly rent gap
    ROUND(r.monthly_rent - (i.median_household_income * 0.30 / 12), 2) AS monthly_rent_gap,

    -- Cost burden flags
    CASE WHEN r.annual_rent / NULLIF(i.median_household_income,0) > 0.30 THEN 1 ELSE 0 END AS is_cost_burdened,
    CASE WHEN r.annual_rent / NULLIF(i.median_household_income,0) > 0.50 THEN 1 ELSE 0 END AS is_severely_burdened,

    -- Home Price-to-Income Ratio
    CASE
        WHEN i.median_household_income > 0
        THEN ROUND(
            COALESCE(hpm.median_home_price, hpl.median_home_price)
            / i.median_household_income, 2)
        ELSE NULL
    END AS home_price_to_income_ratio,

    -- Estimated monthly mortgage (PMT, 20% down, 30yr)
    CASE
        WHEN COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) > 0
        AND  COALESCE(hpm.median_home_price, hpl.median_home_price) > 0
        THEN ROUND(
            (COALESCE(hpm.median_home_price, hpl.median_home_price) * 0.80) *
            (
                (COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12) *
                POWER(1 + COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12, 360)
            ) /
            (
                POWER(1 + COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12, 360) - 1
            ), 2)
        ELSE NULL
    END AS est_monthly_mortgage,

    -- Mortgage to income ratio
    CASE
        WHEN i.median_household_income > 0
        AND  COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) > 0
        AND  COALESCE(hpm.median_home_price, hpl.median_home_price) > 0
        THEN ROUND(
            (
                (COALESCE(hpm.median_home_price, hpl.median_home_price) * 0.80) *
                (
                    (COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12) *
                    POWER(1 + COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12, 360)
                ) /
                (
                    POWER(1 + COALESCE(mo.rate_30yr_fixed, ml.rate_30yr_fixed) / 100.0 / 12, 360) - 1
                ) * 12
            ) / i.median_household_income, 4)
        ELSE NULL
    END AS mortgage_to_income_ratio,

    -- Down payment required (20%)
    ROUND(COALESCE(hpm.median_home_price, hpl.median_home_price) * 0.20, 2) AS down_payment_required

FROM rent r
JOIN prod.dim_geography g ON r.geo_id = g.geo_id

-- Income: latest ACS year only
LEFT JOIN income_latest i
    ON r.geo_id = i.geo_id
    AND i.rn = 1

-- Labor: exact year+month match
LEFT JOIN labor lm
    ON r.geo_id = lm.geo_id
    AND lm.year  = r.year
    AND lm.month = r.month

-- Labor fallback: latest available row per city
LEFT JOIN (
    SELECT geo_id, unemployment_rate, employment_level,
           ROW_NUMBER() OVER (PARTITION BY geo_id ORDER BY year DESC, month DESC) AS rn
    FROM labor
) lb ON r.geo_id = lb.geo_id AND lb.rn = 1

-- Home prices: exact year+month match
LEFT JOIN home_prices hpm
    ON r.geo_id    = hpm.geo_id
    AND hpm.year   = r.year
    AND hpm.month  = r.month
    AND hpm.home_type = 'All Homes'

-- Home prices fallback: latest available per city
LEFT JOIN (
    SELECT geo_id, median_home_price,
           ROW_NUMBER() OVER (PARTITION BY geo_id ORDER BY year DESC, month DESC) AS rn
    FROM home_prices
    WHERE home_type = 'All Homes'
) hpl ON r.geo_id = hpl.geo_id AND hpl.rn = 1

-- Mortgage: exact year+month match
LEFT JOIN mortgage mo
    ON mo.year  = r.year
    AND mo.month = r.month

-- Mortgage fallback: latest available
CROSS JOIN mortgage_latest ml

WHERE g.is_active = 1;
GO

-- ============================================================
-- Rebuild vw_latest_snapshot
-- ============================================================
CREATE VIEW prod.vw_latest_snapshot AS
SELECT a.*
FROM prod.vw_affordability_metrics a
INNER JOIN (
    SELECT geo_id, bedroom_type, MAX(full_date) AS max_date
    FROM prod.vw_affordability_metrics
    GROUP BY geo_id, bedroom_type
) latest
    ON  a.geo_id       = latest.geo_id
    AND a.bedroom_type = latest.bedroom_type
    AND a.full_date    = latest.max_date;
GO

-- ============================================================
-- Rebuild vw_city_classification
-- ============================================================
CREATE VIEW prod.vw_city_classification AS
WITH latest AS (
    SELECT
        geo_id,
        city_display,
        state_abbr,
        region,
        rent_to_income_ratio,
        unemployment_rate,
        median_household_income,
        full_date,
        ROW_NUMBER() OVER (PARTITION BY geo_id ORDER BY full_date DESC) AS rn
    FROM prod.vw_affordability_metrics
    WHERE bedroom_type = 'All Homes'
),
medians AS (
    SELECT
        AVG(rent_to_income_ratio) AS median_rti,
        AVG(unemployment_rate)    AS median_unemp
    FROM latest WHERE rn = 1
)
SELECT
    l.geo_id,
    l.city_display,
    l.state_abbr,
    l.region,
    l.rent_to_income_ratio,
    l.unemployment_rate,
    l.median_household_income,
    CASE
        WHEN l.rent_to_income_ratio <= m.median_rti AND l.unemployment_rate <= m.median_unemp
            THEN 'Opportunity City'
        WHEN l.rent_to_income_ratio >  m.median_rti AND l.unemployment_rate <= m.median_unemp
            THEN 'Lifestyle Premium City'
        WHEN l.rent_to_income_ratio <= m.median_rti AND l.unemployment_rate >  m.median_unemp
            THEN 'Budget Risk City'
        WHEN l.rent_to_income_ratio >  m.median_rti AND l.unemployment_rate >  m.median_unemp
            THEN 'Pressure City'
        ELSE 'Unclassified'
    END AS city_classification
FROM latest l
CROSS JOIN medians m
WHERE l.rn = 1;
GO

-- ============================================================
-- Validation
-- ============================================================
SELECT
    city_display,
    full_date,
    monthly_rent,
    median_household_income,
    unemployment_rate,
    rent_to_income_ratio,
    est_monthly_mortgage,
    mortgage_to_income_ratio
FROM prod.vw_latest_snapshot
WHERE bedroom_type = 'All Homes'
ORDER BY rent_to_income_ratio DESC;
GO

PRINT 'All views rebuilt successfully.';
GO
