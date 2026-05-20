# U.S. City Affordability & Economic Opportunity Dashboard

A data engineering and analytics portfolio project that measures housing affordability across the 25 largest U.S. metro areas using a full Python → SQL Server → Power BI pipeline.

---

## The Core Question

> **Which U.S. cities offer the best affordability-adjusted quality of economic opportunity?**

This dashboard does not ask which cities are cheapest. It asks which cities offer the best balance between housing costs, local income, job-market strength, and how quickly these variables are changing over time.

A cheap city with weak wages and high unemployment may not be truly affordable. A high-cost city with very high wages and strong job growth may be more manageable than it first appears.

---

## Dashboard Pages

| Page | Purpose |
|---|---|
| Executive Overview | U.S. map, affordability pressure rankings, income vs rent scatter, key insight card |
| Rent Affordability | Rent burden by city, rent trend 2015–2026, rent vs income growth, what-if income slider |
| Homeownership Affordability | Price-to-income ratio, estimated mortgage payments, years to save down payment, what-if calculator |
| City Comparison Tool | Side-by-side city comparison, head-to-head metrics table, budget impact analysis, city classification |
| Methodology & Data Sources | Metric definitions, data sources, affordability pressure score formula, assumptions |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Data extraction & transformation | Python (pandas, requests, pyodbc) |
| Data storage & modeling | SQL Server 2019 (local) |
| Visualization | Power BI Desktop |
| Scheduling | Windows Task Scheduler (monthly) |

---

## Data Sources

| Source | Dataset | Frequency | Coverage |
|---|---|---|---|
| Zillow | ZORI — Observed Rent Index | Monthly | 2015–2026 |
| Zillow | ZHVI — Home Value Index | Monthly | 2015–2026 |
| U.S. Census ACS | Median Household Income (B19013) | Annual | 2015–2024 |
| BLS LAUS | Local Area Unemployment Statistics | Monthly | 2015–2025 |
| FRED | 30-Year Fixed Mortgage Rate (MORTGAGE30US) | Monthly | 2015–2026 |

---

## Key Metrics

| Metric | Formula | Why It Matters |
|---|---|---|
| Rent-to-Income Ratio | Annual rent ÷ median household income | Measures renter burden — above 0.30 = cost burdened |
| Home Price-to-Income Ratio | Median home price ÷ median income | Measures ownership affordability — above 5x = severely unaffordable |
| Est. Monthly Mortgage | PMT formula — 30yr, adjustable rate and down payment | Converts home price into monthly payment reality |
| Mortgage-to-Income Ratio | Annual mortgage ÷ median income | Above 0.28 = unaffordable by conventional standards |
| Rent Growth YoY | (Current rent − Prior year rent) ÷ Prior year rent | Shows whether rents are accelerating |
| Income Growth YoY | (Current income − Prior year income) ÷ Prior year income | Measures whether purchasing power is keeping up |
| Years to Save Down Payment | Down payment ÷ (10% of annual income) | Measures barrier to homeownership entry |
| Affordability Pressure Score | Composite index — see formula below | Single number summarizing overall housing stress |

### Affordability Pressure Score Formula

```
Score = (Rent-to-Income ÷ 0.30) × 40
      + (Mortgage-to-Income ÷ 0.28) × 40
      + (Unemployment Rate ÷ 5%) × 20
```

A score of 100 means a city hits all three affordability thresholds simultaneously. Above 100 indicates extreme stress on one or more dimensions.

---

## City Classifications

Each city is classified into one of four categories based on its rent burden and unemployment rate relative to the 25-city median:

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

### Fact Tables
- `prod.fact_rent`
- `prod.fact_home_prices`
- `prod.fact_income`
- `prod.fact_labor`
- `prod.fact_mortgage_rates`

### Dimension Tables
- `prod.dim_geography` — 25 metros with coordinates, region, and crosswalk codes
- `prod.dim_date` — 2015–2026 date spine
- `prod.dim_scenario` — what-if parameter presets

### Views (Power BI connects here)
- `prod.vw_affordability_metrics` — pre-computed affordability metrics with fallback joins for data lag
- `prod.vw_latest_snapshot` — most recent data point per city
- `prod.vw_city_classification` — dynamic city classification quadrant

---

## ETL Pipeline

Five Python scripts extract, clean, and load data into SQL Server. A master runner script orchestrates all five in sequence.

```
run_etl.py
├── etl_zillow_zori.py      # Rent data
├── etl_zillow_zhvi.py      # Home price data
├── etl_census_acs.py       # Income data (requires Census API key)
├── etl_bls_laus.py         # Unemployment data (requires BLS API key)
└── etl_fred_mortgage.py    # Mortgage rate data
```

Each script follows the same pattern:
1. Download from source API or CSV
2. Parse and normalize to canonical metro names
3. Truncate and load staging table
4. Load production fact table via SQL join
5. Run validation query and log results

### Scheduling

The pipeline runs monthly via Windows Task Scheduler using `run_etl.bat`. All ETL activity is logged to `/logs/run_etl.log`.

---

## Project Structure

```
City Dashboard/
├── run_etl.py                  # Master runner
├── run_etl.bat                 # Task Scheduler entry point
├── db_utils.py                 # Shared SQL Server connection
├── etl_zillow_zori.py
├── etl_zillow_zhvi.py
├── etl_census_acs.py
├── etl_bls_laus.py
├── etl_fred_mortgage.py
├── create_database.sql         # Full schema creation script
├── fix_views_v2.sql            # Production view definitions
├── logs/
│   ├── run_etl.log
│   ├── etl_zillow_zori.log
│   ├── etl_zillow_zhvi.log
│   ├── etl_census_acs.log
│   ├── etl_bls_laus.log
│   └── etl_fred_mortgage.log
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

### Installation

**1. Clone the repository**
```bash
git clone https://github.com/Si944-byte/city-affordability-dashboard.git
cd city-affordability-dashboard
```

**2. Install Python dependencies**
```bash
pip install pandas requests pyodbc
```

**3. Create the database**

Run `create_database.sql` in SSMS against your SQL Server instance. This creates the `CityAffordability` database, all schemas, tables, and seeds dimension data.

**4. Configure API keys**

Open `etl_census_acs.py` and set:
```python
CENSUS_API_KEY = "your_key_here"
```

Open `etl_bls_laus.py` and set:
```python
BLS_API_KEY = "your_key_here"
```

**5. Update the connection string**

Open `db_utils.py` and update the server name if different from the default:
```python
CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=YOUR_SERVER_NAME;"
    "DATABASE=CityAffordability;"
    "Trusted_Connection=yes;"
)
```

**6. Run the ETL pipeline**
```bash
python run_etl.py
```

**7. Connect Power BI**

Open Power BI Desktop → Get Data → SQL Server → connect to your instance → import `prod.affordability_final`, `prod.dim_geography`, `prod.dim_date`, `prod.dim_scenario`, and `prod.vw_city_classification`.

Apply the theme file `CityAffordability_Theme.json` via View → Themes → Browse for themes.

---

## Key Insights

**1. Coastal metros dominate affordability pressure**
Los Angeles (119), New York (104), and San Diego (102) lead the Affordability Pressure Score — driven by home price-to-income ratios above 8x and rent-to-income ratios well above the 30% threshold.

**2. Rent growth is outpacing income growth in most cities**
In 2024, average rent growth across the top 25 metros ran ahead of income growth, widening the affordability gap. Cities where rent growth exceeds income growth are becoming structurally less affordable over time regardless of current price levels.

**3. Midwest cities offer the strongest opportunity-to-cost balance**
Minneapolis, St. Louis, and Chicago offer moderate rents relative to income with competitive labor markets — making them the strongest Opportunity City candidates in the dataset.

**4. Homeownership barriers are severe in West Coast markets**
At 10% annual savings, a household in Los Angeles would need nearly 15 years to save a 20% down payment on the median home. In St. Louis, the same household could save a down payment in approximately 6 years.

**5. Moving from a Pressure City to an Opportunity City generates significant savings**
A household earning $75,000 annually moving from Miami to Minneapolis would save approximately $1,000/month — over $12,000 per year — based on 2024 rent data.

---

## Future Improvements

- [ ] Add CPI and inflation data for real wage growth calculation
- [ ] Add population and migration data from Census ACS
- [ ] Build affordability Z-score to flag cities with historically stretched conditions
- [ ] Add rent-income divergence metric showing cumulative gap since 2015
- [ ] Expand to top 50 metros
- [ ] Add Python-based forecasting (Prophet or ARIMA) for rent and affordability trends
- [ ] Publish to Power BI Service for web access
- [ ] Add HUD Fair Market Rents as a supplementary rent benchmark

---

## Author

**Si944-byte**
GitHub: https://github.com/Si944-byte

---

## Data Disclaimer

All data is sourced from publicly available government and research datasets. Zillow data is used under Zillow's research data terms. Census ACS, BLS LAUS, and FRED data are public domain. This project is for educational and portfolio purposes only.
