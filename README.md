# U.S. City Affordability & Economic Opportunity Dashboard

An end-to-end Power BI and SQL analytics project that measures housing affordability pressure across the 25 largest U.S. metros using rent, home value, income, unemployment, and mortgage-rate data.

---

## The Core Question

> **Which U.S. cities offer the best affordability-adjusted quality of economic opportunity?**

This dashboard does not ask which cities are cheapest. It asks which cities offer the best balance between housing costs, local income, job-market strength, and how quickly these variables are changing over time.

A cheap city with weak wages and high unemployment may not be truly affordable. A high-cost city with very high wages and strong job growth may be more manageable than it first appears.

---

## Dashboard Screenshots

### Executive Overview
<img width="1280" height="719" alt="Page 1" src="https://github.com/user-attachments/assets/b9e274aa-dff9-45a9-8c74-766c5f2adfc9" />

### Rent Affordability
<img width="1280" height="720" alt="Page 2" src="https://github.com/user-attachments/assets/171932da-51bc-49c3-ae61-b9b9a5adffaf" />

### Homeownership Affordability
<img width="1278" height="720" alt="Page 3" src="https://github.com/user-attachments/assets/30480802-e470-45d6-ab9f-bbb6f051dc35" />

### City Comparison Tool
<img width="1278" height="719" alt="Page 4" src="https://github.com/user-attachments/assets/86dde315-b90d-4828-bfcb-d8cc3af6ca71" />

### Affordability Signals
<img width="1279" height="719" alt="Page 5 (Affordability)" src="https://github.com/user-attachments/assets/7d95ce79-12da-4320-a92f-793d141f5f46" />

### Methodology
<img width="1442" height="811" alt="Page 5" src="https://github.com/user-attachments/assets/18ade717-bc12-4970-a897-40cb60ed471d" />

---

## Dashboard Pages

| Page | Purpose |
|---|---|
| Executive Overview | U.S. map, affordability pressure rankings, income vs rent scatter, key insight card |
| Rent Affordability | Rent burden by city, rent trend 2015–2026, rent vs income growth, what-if income slider |
| Homeownership Affordability | Price-to-income ratio, estimated mortgage payments, years to save down payment, what-if calculator |
| City Comparison Tool | Side-by-side city comparison, head-to-head metrics table, budget impact analysis, city classification |
| Affordability Signals | Z-scores, rent-income divergence since 2015, top 5 stressed cities trend, divergence vs pressure scatter |
| Methodology & Data Sources | Metric definitions, data sources, affordability pressure score formula, assumptions |

---

## Pipeline Architecture

```
Public Data Sources
(Zillow, Census, BLS, FRED, HUD)
            │
            ▼
  Python ETL Scripts
  (extract, clean, normalize)
            │
            ▼
  SQL Server — Staging Schema
  (raw data, truncate on each load)
            │
            ▼
  SQL Server — Production Schema
  (fact tables, dimension tables, views)
            │
            ▼
  prod.affordability_final
  (pre-computed flat table)
            │
            ▼
  Power BI Desktop
  (import mode, DAX measures)
            │
            ▼
  Interactive Dashboard
  (6 pages, what-if parameters, city comparison)
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| Data extraction & transformation | Python (pandas, requests, pyodbc) |
| Data storage & modeling | SQL Server 2019 (local) |
| Visualization | Power BI Desktop |
| Scheduling | Windows Task Scheduler (monthly) |
| Configuration | python-dotenv (.env file) |

---

## Data Sources

| Source | Dataset | Frequency | Coverage |
|---|---|---|---|
| Zillow | ZORI — Observed Rent Index | Monthly | 2015–2026 |
| Zillow | ZHVI — Home Value Index | Monthly | 2015–2026 |
| U.S. Census ACS | Median Household Income (B19013) | Annual | 2015–2024 |
| BLS LAUS | Local Area Unemployment Statistics | Monthly | 2015–2025 |
| FRED | 30-Year Fixed Mortgage Rate (MORTGAGE30US) | Monthly | 2015–2026 |
| HUD | Fair Market Rents (FMR) | Annual | 2015–2024 |

---

## Key Metrics

| Metric | Formula | Why It Matters |
|---|---|---|
| Rent-to-Income Ratio | Annual rent ÷ median household income | Above 0.30 = cost burdened |
| Home Price-to-Income Ratio | Median home price ÷ median income | Above 5x = severely unaffordable |
| Est. Monthly Mortgage | PMT formula — 30yr, adjustable rate and down payment | Converts home price to monthly reality |
| Mortgage-to-Income Ratio | Annual mortgage ÷ median income | Above 0.28 = unaffordable |
| Rent Growth YoY | (Current rent − Prior year rent) ÷ Prior year rent | Shows whether rents are accelerating |
| Income Growth YoY | (Current income − Prior year income) ÷ Prior year income | Measures purchasing power change |
| Years to Save Down Payment | Down payment ÷ (10% of annual income) | Measures barrier to homeownership |
| Affordability Pressure Score | Composite index — see formula below | Single number summarizing housing stress |
| Affordability Z-Score | (Current RTI − Historical avg RTI) ÷ Historical std dev | Flags historically stretched conditions |
| Rent-Income Divergence | Cumulative rent growth − cumulative income growth since 2015 | Shows structural affordability deterioration |

### Affordability Pressure Score Formula

```
Score = (Rent-to-Income ÷ 0.30) × 40
      + (Mortgage-to-Income ÷ 0.28) × 40
      + (Unemployment Rate ÷ 5%) × 20
```

A score of 100 means a city hits all three affordability thresholds simultaneously.
Above 100 indicates extreme stress on one or more dimensions.

---

## Key Insights

**1. Coastal metros dominate affordability pressure**
Los Angeles (156), San Diego (139), and New York (128) lead the Affordability Pressure Score — driven by home price-to-income ratios above 8x and rent-to-income ratios well above the 30% threshold.

**2. Rent growth is outpacing income growth in most cities**
In 2024, average rent growth across the top 25 metros ran ahead of income growth, widening the affordability gap. Tampa and Las Vegas show the largest cumulative divergence since 2015 — over 24%.

**3. Affordability stress is spreading beyond coastal cities**
St. Louis and Philadelphia — historically among the most affordable cities in America — now show Z-scores above 2, meaning rent burden has reached historically unusual levels relative to their own baselines.

**4. Homeownership barriers are severe in West Coast markets**
At 10% annual savings, a household in Los Angeles would need nearly 15 years to save a 20% down payment on the median home. In St. Louis, the same household could save a down payment in approximately 3 years.

**5. Moving from a Pressure City to an Opportunity City generates significant savings**
A household earning $75,000 annually moving from Miami to Minneapolis would save approximately $1,000/month — over $12,000 per year — based on 2024 rent data.

---

## Research Questions

- Which cities have the largest gap between rent growth and income growth since 2015?
- Are high-growth labor markets becoming less affordable faster than slower-growth cities?
- Which cities offer the best affordability-adjusted economic opportunity?
- Can rent-income divergence identify affordability stress before rent burden crosses 30%?
- Which cities are affordable because incomes are high versus because housing is cheap?
- How sensitive is homeownership affordability to mortgage-rate increases?

---

## City Classifications

| Classification | Conditions | Interpretation |
|---|---|---|
| Opportunity City | Low rent burden + low unemployment | Affordable with strong job market |
| Lifestyle Premium City | High rent burden + low unemployment | Expensive but strong income and jobs |
| Budget Risk City | Low rent burden + high unemployment | Cheap but weak labor market |
| Pressure City | High rent burden + high unemployment | Expensive with weak job market |

---

## Database Architecture

Built on a star schema in SQL Server with two schemas — `staging` for raw data and `prod` for clean fact/dimension tables.

### Staging Tables
- `staging.rent`
- `staging.home_prices`
- `staging.income`
- `staging.labor`
- `staging.mortgage_rates`
- `staging.hud_fmr`

### Fact Tables
- `prod.fact_rent`
- `prod.fact_home_prices`
- `prod.fact_income`
- `prod.fact_labor`
- `prod.fact_mortgage_rates`
- `prod.fact_hud_fmr`

### Dimension Tables
- `prod.dim_geography` — 25 metros with coordinates, region, and crosswalk codes
- `prod.dim_date` — 2015–2026 date spine
- `prod.dim_scenario` — what-if parameter presets

### Key Views & Tables (Power BI connects here)
- `prod.vw_affordability_metrics` — pre-computed affordability metrics with fallback joins
- `prod.vw_latest_snapshot` — most recent data point per city
- `prod.vw_city_classification` — dynamic city classification quadrant
- `prod.affordability_final` — materialized flat table for Power BI import performance

---

## ETL Pipeline

Six Python scripts extract, clean, and load data into SQL Server. A master runner script orchestrates all six in sequence.

```
run_etl.py
├── etl_zillow_zori.py      # Rent data
├── etl_zillow_zhvi.py      # Home price data
├── etl_census_acs.py       # Income data        (requires Census API key)
├── etl_bls_laus.py         # Unemployment data  (requires BLS API key)
├── etl_fred_mortgage.py    # Mortgage rate data
└── etl_hud_fmr.py          # Fair market rents  (requires HUD API key)
```

Each script follows the same pattern:
1. Download from source API or CSV
2. Parse and normalize to canonical metro names
3. Truncate and load staging table
4. Load production fact table via SQL join
5. Run validation query and log results

### Scheduling
The pipeline runs monthly via Windows Task Scheduler using `run_etl.bat`.
All ETL activity is logged to `logs/run_etl.log`.

---

## Project Structure

```
city-affordability-dashboard/
├── run_etl.py                    # Master pipeline runner
├── run_etl.bat                   # Task Scheduler entry point
├── db_utils.py                   # Shared SQL Server connection
├── etl_zillow_zori.py            # Rent ETL
├── etl_zillow_zhvi.py            # Home price ETL
├── etl_census_acs.py             # Income ETL
├── etl_bls_laus.py               # Unemployment ETL
├── etl_fred_mortgage.py          # Mortgage rate ETL
├── etl_hud_fmr.py                # HUD fair market rents ETL
├── create_database.sql           # Full schema creation script
├── fix_views_v2.sql              # Production view definitions
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment variable template
├── .gitignore                    # Files excluded from version control
├── screenshots/                  # Dashboard page screenshots
│   ├── page1_executive_overview.png
│   ├── page2_rent_affordability.png
│   ├── page3_homeownership.png
│   ├── page4_city_comparison.png
│   ├── page5_methodology.png
│   └── page6_affordability_signals.png
├── logs/                         # ETL run logs (excluded from git)
│   ├── run_etl.log
│   ├── etl_zillow_zori.log
│   ├── etl_zillow_zhvi.log
│   ├── etl_census_acs.log
│   ├── etl_bls_laus.log
│   ├── etl_fred_mortgage.log
│   └── etl_hud_fmr.log
└── CityAffordability_Theme.json  # Power BI theme file
```

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- SQL Server 2019 (local) with ODBC Driver 17
- Power BI Desktop
- Census API key — free at https://api.census.gov/data/key_signup.html
- BLS API key — free at https://data.bls.gov/registrationEngine/
- HUD API key — free at https://www.huduser.gov/portal/dataset/fmr-api.html

### Installation

**1. Clone the repository**
```bash
git clone https://github.com/Si944-byte/city-affordability-dashboard.git
cd city-affordability-dashboard
```

**2. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3. Configure environment variables**
```bash
cp .env.example .env
```
Open `.env` and fill in your SQL Server name and API keys.

**4. Create the database**

Run `create_database.sql` in SSMS against your SQL Server instance.
Then run `fix_views_v2.sql` to create production views.

**5. Run the ETL pipeline**
```bash
python run_etl.py
```

**6. Connect Power BI**

Open Power BI Desktop → Get Data → SQL Server → connect to your instance → import:
- `prod.affordability_final`
- `prod.dim_geography`
- `prod.dim_date`
- `prod.dim_scenario`
- `prod.vw_city_classification`

Apply theme: View → Themes → Browse → select `CityAffordability_Theme.json`

---

## Assumptions & Limitations

- **Income data lags ~1 year.** Census ACS 2024 data (released January 2026) is the most recent available. For months beyond the latest ACS release, the most recent income figure is carried forward.
- **Mortgage calculations** use a 30-year fixed rate, 20% down payment at default settings, and the national average rate from FRED. These are adjustable via slicers on the Homeownership page.
- **The 30% rent-to-income threshold** and 28% mortgage-to-income benchmark are general standards established by HUD and the CFPB — not absolute limits.
- **Metro coverage** is limited to the top 25 U.S. metros by population. Smaller metros with more extreme affordability conditions are excluded by design.
- **This project is for educational and portfolio purposes only.** It does not constitute financial, real estate, or relocation advice.

---

## Future Improvements

- [ ] Add CPI and inflation data for real wage growth calculation
- [ ] Add population and migration data from Census ACS
- [ ] Add Python-based forecasting (Prophet) for rent and affordability trends
- [ ] Build city affordability clustering (k-means archetypes)
- [ ] Add affordability shock detection (anomaly detection)
- [ ] Add regression modeling to identify key affordability drivers
- [ ] Expand to top 50 metros
- [ ] Publish to Power BI Service for web access

---

## Author

**Si944-byte**
GitHub: https://github.com/Si944-byte

---

## Data Disclaimer

All data is sourced from publicly available government and research datasets. Zillow data is used under Zillow's research data terms. Census ACS, BLS LAUS, FRED, and HUD data are public domain. This project is for educational and portfolio purposes only.
