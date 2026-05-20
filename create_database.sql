-- ============================================================
-- City Affordability & Economic Opportunity Dashboard
-- Database & Schema Creation Script
-- Server: DESKTOP-1CRNFTD | SQL Server 2019
-- ============================================================

-- ============================================================
-- STEP 1: CREATE DATABASE
-- ============================================================

USE master;
GO

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'CityAffordability')
BEGIN
    CREATE DATABASE CityAffordability;
END
GO

USE CityAffordability;
GO

-- ============================================================
-- STEP 2: CREATE SCHEMAS
-- ============================================================

IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'staging')
    EXEC('CREATE SCHEMA staging');
GO

IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'prod')
    EXEC('CREATE SCHEMA prod');
GO


-- ============================================================
-- STEP 3: STAGING TABLES
-- Raw data lands here first. ETL truncates before each load.
-- ============================================================

-- ------------------------------------------------------------
-- staging.rent  (Zillow ZORI)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.rent', 'U') IS NOT NULL DROP TABLE staging.rent;
GO

CREATE TABLE staging.rent (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    metro_raw       NVARCHAR(200)   NOT NULL,   -- raw metro name from source
    report_date     DATE            NOT NULL,
    monthly_rent    DECIMAL(10,2)   NULL,
    bedroom_type    NVARCHAR(50)    NULL,        -- All Homes, 1br, 2br etc
    data_source     NVARCHAR(50)    NOT NULL DEFAULT 'Zillow ZORI',
    loaded_at       DATETIME        NOT NULL DEFAULT GETDATE()
);
GO

-- ------------------------------------------------------------
-- staging.home_prices  (Zillow ZHVI)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.home_prices', 'U') IS NOT NULL DROP TABLE staging.home_prices;
GO

CREATE TABLE staging.home_prices (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    metro_raw       NVARCHAR(200)   NOT NULL,
    report_date     DATE            NOT NULL,
    median_home_price DECIMAL(12,2) NULL,
    home_type       NVARCHAR(50)    NULL,        -- All Homes, SFR etc
    data_source     NVARCHAR(50)    NOT NULL DEFAULT 'Zillow ZHVI',
    loaded_at       DATETIME        NOT NULL DEFAULT GETDATE()
);
GO

-- ------------------------------------------------------------
-- staging.income  (Census ACS)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.income', 'U') IS NOT NULL DROP TABLE staging.income;
GO

CREATE TABLE staging.income (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    metro_raw               NVARCHAR(200)   NOT NULL,
    survey_year             INT             NOT NULL,
    median_household_income DECIMAL(12,2)   NULL,
    per_capita_income       DECIMAL(12,2)   NULL,
    population              BIGINT          NULL,
    data_source             NVARCHAR(50)    NOT NULL DEFAULT 'Census ACS',
    loaded_at               DATETIME        NOT NULL DEFAULT GETDATE()
);
GO

-- ------------------------------------------------------------
-- staging.labor  (BLS LAUS)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.labor', 'U') IS NOT NULL DROP TABLE staging.labor;
GO

CREATE TABLE staging.labor (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    metro_raw           NVARCHAR(200)   NOT NULL,
    report_date         DATE            NOT NULL,
    unemployment_rate   DECIMAL(5,2)    NULL,
    employment_level    BIGINT          NULL,
    labor_force         BIGINT          NULL,
    data_source         NVARCHAR(50)    NOT NULL DEFAULT 'BLS LAUS',
    loaded_at           DATETIME        NOT NULL DEFAULT GETDATE()
);
GO

-- ------------------------------------------------------------
-- staging.mortgage_rates  (FRED - 30yr Fixed National)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.mortgage_rates', 'U') IS NOT NULL DROP TABLE staging.mortgage_rates;
GO

CREATE TABLE staging.mortgage_rates (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    report_date     DATE            NOT NULL,
    rate_30yr_fixed DECIMAL(6,4)    NULL,       -- e.g. 6.8500
    data_source     NVARCHAR(50)    NOT NULL DEFAULT 'FRED',
    loaded_at       DATETIME        NOT NULL DEFAULT GETDATE()
);
GO

-- ------------------------------------------------------------
-- staging.cpi  (BLS CPI - Metro + National)
-- ------------------------------------------------------------
IF OBJECT_ID('staging.cpi', 'U') IS NOT NULL DROP TABLE staging.cpi;
GO

CREATE TABLE staging.cpi (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    metro_raw       NVARCHAR(200)   NULL,        -- NULL = national
    report_date     DATE            NOT NULL,
    cpi_index       DECIMAL(10,4)   NULL,
    cpi_category    NVARCHAR(100)   NULL,        -- All Items, Shelter etc
    is_national     BIT             NOT NULL DEFAULT 0,
    data_source     NVARCHAR(50)    NOT NULL DEFAULT 'BLS CPI',
    loaded_at       DATETIME        NOT NULL DEFAULT GETDATE()
);
GO


-- ============================================================
-- STEP 4: DIMENSION TABLES
-- ============================================================

-- ------------------------------------------------------------
-- prod.dim_geography  (Master metro list + crosswalk)
-- The spine that all fact tables join to.
-- ------------------------------------------------------------
IF OBJECT_ID('prod.dim_geography', 'U') IS NOT NULL DROP TABLE prod.dim_geography;
GO

CREATE TABLE prod.dim_geography (
    geo_id          INT IDENTITY(1,1) PRIMARY KEY,
    metro_name      NVARCHAR(200)   NOT NULL,   -- canonical name used everywhere
    city_display    NVARCHAR(100)   NOT NULL,   -- short display name e.g. "New York"
    state_abbr      NCHAR(2)        NOT NULL,
    region          NVARCHAR(50)    NOT NULL,   -- Northeast, South, Midwest, West
    census_cbsa     NVARCHAR(20)    NULL,       -- Census CBSA code
    zillow_name     NVARCHAR(200)   NULL,       -- raw Zillow metro label
    bls_area_code   NVARCHAR(20)    NULL,       -- BLS LAUS area code
    latitude        DECIMAL(9,6)    NULL,
    longitude       DECIMAL(9,6)    NULL,
    is_active       BIT             NOT NULL DEFAULT 1
);
GO

-- ------------------------------------------------------------
-- prod.dim_date
-- ------------------------------------------------------------
IF OBJECT_ID('prod.dim_date', 'U') IS NOT NULL DROP TABLE prod.dim_date;
GO

CREATE TABLE prod.dim_date (
    date_id         INT             PRIMARY KEY,  -- YYYYMMDD format
    full_date       DATE            NOT NULL,
    year            SMALLINT        NOT NULL,
    quarter         TINYINT         NOT NULL,
    month           TINYINT         NOT NULL,
    month_name      NVARCHAR(10)    NOT NULL,
    day_of_month    TINYINT         NOT NULL,
    is_year_end     BIT             NOT NULL DEFAULT 0
);
GO

-- ------------------------------------------------------------
-- prod.dim_scenario  (what-if parameters for Power BI)
-- ------------------------------------------------------------
IF OBJECT_ID('prod.dim_scenario', 'U') IS NOT NULL DROP TABLE prod.dim_scenario;
GO

CREATE TABLE prod.dim_scenario (
    scenario_id         INT IDENTITY(1,1) PRIMARY KEY,
    scenario_name       NVARCHAR(100)   NOT NULL,
    mortgage_rate       DECIMAL(6,4)    NULL,
    down_payment_pct    DECIMAL(5,2)    NULL,
    income_assumption   DECIMAL(12,2)   NULL,
    loan_term_years     INT             NULL DEFAULT 30
);
GO


-- ============================================================
-- STEP 5: FACT TABLES
-- ============================================================

-- ------------------------------------------------------------
-- prod.fact_rent
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_rent', 'U') IS NOT NULL DROP TABLE prod.fact_rent;
GO

CREATE TABLE prod.fact_rent (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    geo_id                  INT             NOT NULL,
    date_id                 INT             NOT NULL,
    monthly_rent            DECIMAL(10,2)   NULL,
    annual_rent             AS (monthly_rent * 12) PERSISTED,
    bedroom_type            NVARCHAR(50)    NULL,
    data_source             NVARCHAR(50)    NULL,
    CONSTRAINT fk_rent_geo  FOREIGN KEY (geo_id)  REFERENCES prod.dim_geography(geo_id),
    CONSTRAINT fk_rent_date FOREIGN KEY (date_id) REFERENCES prod.dim_date(date_id)
);
GO

CREATE INDEX ix_fact_rent_geo_date ON prod.fact_rent (geo_id, date_id);
GO

-- ------------------------------------------------------------
-- prod.fact_home_prices
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_home_prices', 'U') IS NOT NULL DROP TABLE prod.fact_home_prices;
GO

CREATE TABLE prod.fact_home_prices (
    id                          INT IDENTITY(1,1) PRIMARY KEY,
    geo_id                      INT             NOT NULL,
    date_id                     INT             NOT NULL,
    median_home_price           DECIMAL(12,2)   NULL,
    home_type                   NVARCHAR(50)    NULL,
    data_source                 NVARCHAR(50)    NULL,
    CONSTRAINT fk_hp_geo        FOREIGN KEY (geo_id)  REFERENCES prod.dim_geography(geo_id),
    CONSTRAINT fk_hp_date       FOREIGN KEY (date_id) REFERENCES prod.dim_date(date_id)
);
GO

CREATE INDEX ix_fact_hp_geo_date ON prod.fact_home_prices (geo_id, date_id);
GO

-- ------------------------------------------------------------
-- prod.fact_income
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_income', 'U') IS NOT NULL DROP TABLE prod.fact_income;
GO

CREATE TABLE prod.fact_income (
    id                          INT IDENTITY(1,1) PRIMARY KEY,
    geo_id                      INT             NOT NULL,
    survey_year                 INT             NOT NULL,
    median_household_income     DECIMAL(12,2)   NULL,
    per_capita_income           DECIMAL(12,2)   NULL,
    population                  BIGINT          NULL,
    data_source                 NVARCHAR(50)    NULL,
    CONSTRAINT fk_inc_geo       FOREIGN KEY (geo_id) REFERENCES prod.dim_geography(geo_id)
);
GO

CREATE INDEX ix_fact_income_geo_year ON prod.fact_income (geo_id, survey_year);
GO

-- ------------------------------------------------------------
-- prod.fact_labor
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_labor', 'U') IS NOT NULL DROP TABLE prod.fact_labor;
GO

CREATE TABLE prod.fact_labor (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    geo_id                  INT             NOT NULL,
    date_id                 INT             NOT NULL,
    unemployment_rate       DECIMAL(5,2)    NULL,
    employment_level        BIGINT          NULL,
    labor_force             BIGINT          NULL,
    data_source             NVARCHAR(50)    NULL,
    CONSTRAINT fk_lab_geo   FOREIGN KEY (geo_id)  REFERENCES prod.dim_geography(geo_id),
    CONSTRAINT fk_lab_date  FOREIGN KEY (date_id) REFERENCES prod.dim_date(date_id)
);
GO

CREATE INDEX ix_fact_labor_geo_date ON prod.fact_labor (geo_id, date_id);
GO

-- ------------------------------------------------------------
-- prod.fact_mortgage_rates
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_mortgage_rates', 'U') IS NOT NULL DROP TABLE prod.fact_mortgage_rates;
GO

CREATE TABLE prod.fact_mortgage_rates (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    date_id         INT             NOT NULL,
    rate_30yr_fixed DECIMAL(6,4)    NULL,
    data_source     NVARCHAR(50)    NULL,
    CONSTRAINT fk_mort_date FOREIGN KEY (date_id) REFERENCES prod.dim_date(date_id)
);
GO

-- ------------------------------------------------------------
-- prod.fact_cpi
-- ------------------------------------------------------------
IF OBJECT_ID('prod.fact_cpi', 'U') IS NOT NULL DROP TABLE prod.fact_cpi;
GO

CREATE TABLE prod.fact_cpi (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    geo_id          INT             NULL,        -- NULL = national CPI
    date_id         INT             NOT NULL,
    cpi_index       DECIMAL(10,4)   NULL,
    cpi_category    NVARCHAR(100)   NULL,
    is_national     BIT             NOT NULL DEFAULT 0,
    data_source     NVARCHAR(50)    NULL,
    CONSTRAINT fk_cpi_date  FOREIGN KEY (date_id) REFERENCES prod.dim_date(date_id)
);
GO


-- ============================================================
-- STEP 6: SEED dim_geography (Top 25 Metros)
-- ============================================================

INSERT INTO prod.dim_geography 
    (metro_name, city_display, state_abbr, region, latitude, longitude)
VALUES
    ('New York-Newark-Jersey City, NY-NJ-PA',   'New York',      'NY', 'Northeast',  40.7128, -74.0060),
    ('Los Angeles-Long Beach-Anaheim, CA',       'Los Angeles',   'CA', 'West',       34.0522, -118.2437),
    ('Chicago-Naperville-Elgin, IL-IN-WI',       'Chicago',       'IL', 'Midwest',    41.8781, -87.6298),
    ('Dallas-Fort Worth-Arlington, TX',          'Dallas',        'TX', 'South',      32.7767, -96.7970),
    ('Houston-The Woodlands-Sugar Land, TX',     'Houston',       'TX', 'South',      29.7604, -95.3698),
    ('Washington-Arlington-Alexandria, DC-VA-MD','Washington DC', 'DC', 'South',      38.9072, -77.0369),
    ('Miami-Fort Lauderdale-Pompano Beach, FL',  'Miami',         'FL', 'South',      25.7617, -80.1918),
    ('Philadelphia-Camden-Wilmington, PA-NJ-DE', 'Philadelphia',  'PA', 'Northeast',  39.9526, -75.1652),
    ('Atlanta-Sandy Springs-Alpharetta, GA',     'Atlanta',       'GA', 'South',      33.7490, -84.3880),
    ('Phoenix-Mesa-Chandler, AZ',                'Phoenix',       'AZ', 'West',       33.4484, -112.0740),
    ('Boston-Cambridge-Newton, MA-NH',           'Boston',        'MA', 'Northeast',  42.3601, -71.0589),
    ('Riverside-San Bernardino-Ontario, CA',     'Riverside',     'CA', 'West',       33.9806, -117.3755),
    ('Seattle-Tacoma-Bellevue, WA',              'Seattle',       'WA', 'West',       47.6062, -122.3321),
    ('Minneapolis-St. Paul-Bloomington, MN-WI',  'Minneapolis',   'MN', 'Midwest',    44.9778, -93.2650),
    ('San Diego-Chula Vista-Carlsbad, CA',       'San Diego',     'CA', 'West',       32.7157, -117.1611),
    ('Tampa-St. Petersburg-Clearwater, FL',      'Tampa',         'FL', 'South',      27.9506, -82.4572),
    ('Denver-Aurora-Lakewood, CO',               'Denver',        'CO', 'West',       39.7392, -104.9903),
    ('St. Louis, MO-IL',                         'St. Louis',     'MO', 'Midwest',    38.6270, -90.1994),
    ('Baltimore-Columbia-Towson, MD',            'Baltimore',     'MD', 'South',      39.2904, -76.6122),
    ('Portland-Vancouver-Hillsboro, OR-WA',      'Portland',      'OR', 'West',       45.5051, -122.6750),
    ('Austin-Round Rock-Georgetown, TX',         'Austin',        'TX', 'South',      30.2672, -97.7431),
    ('Las Vegas-Henderson-Paradise, NV',         'Las Vegas',     'NV', 'West',       36.1699, -115.1398),
    ('San Francisco-Oakland-Berkeley, CA',       'San Francisco', 'CA', 'West',       37.7749, -122.4194),
    ('Charlotte-Concord-Gastonia, NC-SC',        'Charlotte',     'NC', 'South',      35.2271, -80.8431),
    ('Nashville-Davidson-Murfreesboro-Franklin, TN', 'Nashville', 'TN', 'South',      36.1627, -86.7816);
GO


-- ============================================================
-- STEP 7: SEED dim_date (2015 - 2026)
-- ============================================================

WITH dates AS (
    SELECT CAST('2015-01-01' AS DATE) AS d
    UNION ALL
    SELECT DATEADD(DAY, 1, d) FROM dates WHERE d < '2026-12-31'
)
INSERT INTO prod.dim_date (date_id, full_date, year, quarter, month, month_name, day_of_month, is_year_end)
SELECT
    CAST(FORMAT(d, 'yyyyMMdd') AS INT),
    d,
    YEAR(d),
    DATEPART(QUARTER, d),
    MONTH(d),
    DATENAME(MONTH, d),
    DAY(d),
    CASE WHEN MONTH(d) = 12 AND DAY(d) = 31 THEN 1 ELSE 0 END
FROM dates
OPTION (MAXRECURSION 5000);
GO


-- ============================================================
-- STEP 8: SEED dim_scenario (default what-if scenarios)
-- ============================================================

INSERT INTO prod.dim_scenario (scenario_name, mortgage_rate, down_payment_pct, income_assumption, loan_term_years)
VALUES
    ('Conservative - 10% Down, 7.5% Rate',   7.5000, 10.00, NULL, 30),
    ('Moderate - 20% Down, 7.0% Rate',        7.0000, 20.00, NULL, 30),
    ('Optimistic - 20% Down, 6.0% Rate',      6.0000, 20.00, NULL, 30),
    ('Low Income - $50k Household',           7.0000, 10.00, 50000.00, 30),
    ('Mid Income - $75k Household',           7.0000, 10.00, 75000.00, 30),
    ('Mid Income - $100k Household',          7.0000, 20.00, 100000.00, 30),
    ('High Income - $150k Household',         6.5000, 20.00, 150000.00, 30);
GO


-- ============================================================
-- STEP 9: PRODUCTION VIEWS (Power BI connects here)
-- ============================================================

-- ------------------------------------------------------------
-- vw_affordability_metrics
-- Main view. Joins all facts + dims. Pre-computes core metrics.
-- Power BI connects to this as the primary table.
-- ------------------------------------------------------------
IF OBJECT_ID('prod.vw_affordability_metrics', 'V') IS NOT NULL DROP VIEW prod.vw_affordability_metrics;
GO

CREATE VIEW prod.vw_affordability_metrics AS
SELECT
    g.geo_id,
    g.city_display,
    g.metro_name,
    g.state_abbr,
    g.region,
    g.latitude,
    g.longitude,

    -- Date
    d.full_date,
    d.year,
    d.quarter,
    d.month,
    d.month_name,

    -- Rent
    r.monthly_rent,
    r.annual_rent,
    r.bedroom_type,

    -- Income (joined on year -- ACS is annual)
    i.median_household_income,
    i.per_capita_income,
    i.population,

    -- Labor
    l.unemployment_rate,
    l.employment_level,

    -- Home Prices
    hp.median_home_price,

    -- Mortgage Rate (national, joined by date)
    mr.rate_30yr_fixed,

    -- -------------------------------------------------------
    -- COMPUTED AFFORDABILITY METRICS
    -- -------------------------------------------------------

    -- Rent-to-Income Ratio
    CASE 
        WHEN i.median_household_income > 0 
        THEN ROUND(r.annual_rent / i.median_household_income, 4)
        ELSE NULL 
    END AS rent_to_income_ratio,

    -- Affordable monthly rent at 30% threshold
    ROUND(i.median_household_income * 0.30 / 12, 2) AS affordable_monthly_rent,

    -- Monthly rent gap (positive = over budget)
    ROUND(r.monthly_rent - (i.median_household_income * 0.30 / 12), 2) AS monthly_rent_gap,

    -- Cost burden flags
    CASE WHEN r.annual_rent / NULLIF(i.median_household_income, 0) > 0.30 THEN 1 ELSE 0 END AS is_cost_burdened,
    CASE WHEN r.annual_rent / NULLIF(i.median_household_income, 0) > 0.50 THEN 1 ELSE 0 END AS is_severely_burdened,

    -- Home Price-to-Income Ratio
    CASE 
        WHEN i.median_household_income > 0 
        THEN ROUND(hp.median_home_price / i.median_household_income, 2)
        ELSE NULL 
    END AS home_price_to_income_ratio,

    -- Estimated monthly mortgage (PMT approximation, 20% down, 30yr)
    -- PMT = P * [r(1+r)^n] / [(1+r)^n - 1]
    CASE
        WHEN mr.rate_30yr_fixed > 0 AND hp.median_home_price > 0
        THEN ROUND(
            (hp.median_home_price * 0.80) *
            (
                (mr.rate_30yr_fixed / 100 / 12) *
                POWER(1 + mr.rate_30yr_fixed / 100 / 12, 360)
            ) /
            (
                POWER(1 + mr.rate_30yr_fixed / 100 / 12, 360) - 1
            ), 2)
        ELSE NULL
    END AS est_monthly_mortgage,

    -- Mortgage payment to income ratio
    CASE
        WHEN i.median_household_income > 0 AND mr.rate_30yr_fixed > 0 AND hp.median_home_price > 0
        THEN ROUND(
            (
                (hp.median_home_price * 0.80) *
                (
                    (mr.rate_30yr_fixed / 100 / 12) *
                    POWER(1 + mr.rate_30yr_fixed / 100 / 12, 360)
                ) /
                (
                    POWER(1 + mr.rate_30yr_fixed / 100 / 12, 360) - 1
                ) * 12
            ) / i.median_household_income, 4)
        ELSE NULL
    END AS mortgage_to_income_ratio,

    -- Down payment required (20%)
    ROUND(hp.median_home_price * 0.20, 2) AS down_payment_required

FROM prod.fact_rent r
JOIN prod.dim_geography g   ON r.geo_id  = g.geo_id
JOIN prod.dim_date d        ON r.date_id = d.date_id
LEFT JOIN prod.fact_income i
    ON r.geo_id = i.geo_id
    AND i.survey_year = d.year
LEFT JOIN prod.fact_labor l
    ON r.geo_id  = l.geo_id
    AND l.date_id = r.date_id
LEFT JOIN prod.fact_home_prices hp
    ON r.geo_id  = hp.geo_id
    AND hp.date_id = r.date_id
LEFT JOIN prod.fact_mortgage_rates mr
    ON mr.date_id = r.date_id
WHERE g.is_active = 1;
GO


-- ------------------------------------------------------------
-- vw_latest_snapshot
-- Most recent data point per city. Used for KPI cards + map.
-- ------------------------------------------------------------
IF OBJECT_ID('prod.vw_latest_snapshot', 'V') IS NOT NULL DROP VIEW prod.vw_latest_snapshot;
GO

CREATE VIEW prod.vw_latest_snapshot AS
SELECT *
FROM prod.vw_affordability_metrics
WHERE full_date = (
    SELECT MAX(full_date)
    FROM prod.vw_affordability_metrics v2
    WHERE v2.geo_id = prod.vw_affordability_metrics.geo_id
    AND v2.bedroom_type = prod.vw_affordability_metrics.bedroom_type
);
GO


-- ------------------------------------------------------------
-- vw_city_classification
-- Assigns each city to a quadrant: Opportunity, Premium,
-- Budget Risk, or Pressure city. Used on Page 4.
-- ------------------------------------------------------------
IF OBJECT_ID('prod.vw_city_classification', 'V') IS NOT NULL DROP VIEW prod.vw_city_classification;
GO

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
        AVG(rent_to_income_ratio)  AS median_rti,
        AVG(unemployment_rate)     AS median_unemp
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
-- DONE
-- ============================================================

PRINT 'CityAffordability database created successfully.';
PRINT 'Schemas: staging, prod';
PRINT 'Staging tables: rent, home_prices, income, labor, mortgage_rates, cpi';
PRINT 'Dimension tables: dim_geography (25 metros seeded), dim_date (2015-2026), dim_scenario';
PRINT 'Fact tables: fact_rent, fact_home_prices, fact_income, fact_labor, fact_mortgage_rates, fact_cpi';
PRINT 'Views: vw_affordability_metrics, vw_latest_snapshot, vw_city_classification';
