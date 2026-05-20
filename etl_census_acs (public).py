"""
etl_census_acs.py
ETL script: U.S. Census American Community Survey (ACS) 5-Year Estimates
Extracts median household income, per capita income, and population
for the top 25 metros, loads into:
  staging.income  →  prod.fact_income

Source: Census ACS API
Tables: B19013 (Median Household Income), B19301 (Per Capita Income), B01003 (Population)
Geography: Metropolitan Statistical Area (MSA / CBSA)

Get a free API key at: https://api.census.gov/data/key_signup.html
(They email it instantly — takes 2 minutes)

Project: City Affordability Dashboard
Path:    C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard
"""

import os
import sys
import logging
import requests
import pandas as pd
from datetime import datetime

# ----------------------------------------------------------------
# Add project root to path
# ----------------------------------------------------------------
PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)
from db_utils import get_connection

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_census_acs.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------
# !! ENTER YOUR CENSUS API KEY HERE !!
# Get one free at: https://api.census.gov/data/key_signup.html
# ----------------------------------------------------------------
CENSUS_API_KEY = "YOUR_CENSUS_API_KEY_HERE"

# ----------------------------------------------------------------
# Years to pull (ACS 5-year estimates, 2015-2023)
# Note: ACS lags ~1 year. 2023 is the most recent available.
# ----------------------------------------------------------------
YEARS = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023,2024]

# ----------------------------------------------------------------
# Census ACS variables
# B19013_001E = Median Household Income
# B19301_001E = Per Capita Income
# B01003_001E = Total Population
# NAME        = Metro area name
# ----------------------------------------------------------------
ACS_VARIABLES = "NAME,B19013_001E,B19301_001E,B01003_001E"

# ----------------------------------------------------------------
# Metro CBSA codes for our 25 cities
# CBSA = Core Based Statistical Area (Census metro identifier)
# ----------------------------------------------------------------
METRO_CBSA = {
    "35620": "New York",
    "31080": "Los Angeles",
    "16980": "Chicago",
    "19100": "Dallas",
    "26420": "Houston",
    "47900": "Washington DC",
    "33100": "Miami",
    "37980": "Philadelphia",
    "12060": "Atlanta",
    "38060": "Phoenix",
    "14460": "Boston",
    "40140": "Riverside",
    "42660": "Seattle",
    "33460": "Minneapolis",
    "41740": "San Diego",
    "45300": "Tampa",
    "19740": "Denver",
    "41180": "St. Louis",
    "12580": "Baltimore",
    "38900": "Portland",
    "12420": "Austin",
    "29820": "Las Vegas",
    "41860": "San Francisco",
    "16740": "Charlotte",
    "34980": "Nashville",
}


# ----------------------------------------------------------------
# Helper: safe numeric conversion
# ----------------------------------------------------------------
def safe_float(val):
    if val is None:
        return None
    try:
        f = float(val)
        # Census returns -666666666 for missing/suppressed data
        if f < 0:
            return None
        import math
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------
# Step 1: Fetch one year from Census ACS API
# ----------------------------------------------------------------
def fetch_year(year):
    url = (
        f"https://api.census.gov/data/{year}/acs/acs5"
        f"?get={ACS_VARIABLES}"
        f"&for=metropolitan%20statistical%20area/micropolitan%20statistical%20area:*"
        f"&key={CENSUS_API_KEY}"
    )

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        # First row is header
        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        df['survey_year'] = year

        logging.info(f"Fetched ACS {year}: {len(df)} metro rows")
        return df

    except Exception as e:
        logging.error(f"Failed to fetch ACS {year}: {e}")
        return None


# ----------------------------------------------------------------
# Step 2: Download all years and filter to top 25 metros
# ----------------------------------------------------------------
def download_acs():
    logging.info("Downloading Census ACS data...")
    all_frames = []

    for year in YEARS:
        df = fetch_year(year)
        if df is not None:
            all_frames.append(df)

    if not all_frames:
        raise RuntimeError("No ACS data fetched. Check your API key and connection.")

    df_all = pd.concat(all_frames, ignore_index=True)
    logging.info(f"Total rows fetched across all years: {len(df_all)}")
    return df_all


# ----------------------------------------------------------------
# Step 3: Parse and filter to top 25 metros
# ----------------------------------------------------------------
def parse_acs(df_all):
    logging.info("Parsing ACS data...")

    # The CBSA code column is named 'metropolitan statistical area/micropolitan statistical area'
    cbsa_col = 'metropolitan statistical area/micropolitan statistical area'

    if cbsa_col not in df_all.columns:
        # Fallback: find the column containing CBSA codes
        possible = [c for c in df_all.columns if 'statistical' in c.lower() or 'metropolitan' in c.lower()]
        logging.info(f"Available columns: {list(df_all.columns)}")
        if possible:
            cbsa_col = possible[0]
            logging.info(f"Using column: {cbsa_col}")
        else:
            raise ValueError(f"Cannot find CBSA column. Columns: {list(df_all.columns)}")

    # Filter to our 25 CBSAs
    df_filtered = df_all[df_all[cbsa_col].isin(METRO_CBSA.keys())].copy()
    logging.info(f"Matched {df_filtered[cbsa_col].nunique()} of 25 metros")

    matched = set(df_filtered[cbsa_col].unique())
    missing = set(METRO_CBSA.keys()) - matched
    if missing:
        missing_names = {k: METRO_CBSA[k] for k in missing}
        logging.warning(f"Missing CBSAs: {missing_names}")

    # Map CBSA code to city display name
    df_filtered['city_display'] = df_filtered[cbsa_col].map(METRO_CBSA)
    df_filtered['metro_raw'] = df_filtered['NAME']

    # Rename and convert
    df_filtered['median_household_income'] = df_filtered['B19013_001E'].apply(safe_float)
    df_filtered['per_capita_income']       = df_filtered['B19301_001E'].apply(safe_float)
    df_filtered['population']              = df_filtered['B01003_001E'].apply(
        lambda x: int(float(x)) if x and float(x) > 0 else None
    )

    logging.info(f"Parsed {len(df_filtered)} income records")
    return df_filtered


# ----------------------------------------------------------------
# Step 4: Load into staging.income
# ----------------------------------------------------------------
def load_staging(df_filtered):
    logging.info("Loading into staging.income...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE staging.income;")
    conn.commit()
    logging.info("Truncated staging.income")

    insert_sql = """
        INSERT INTO staging.income
            (metro_raw, survey_year, median_household_income,
             per_capita_income, population, data_source)
        VALUES (?, ?, ?, ?, ?, ?)
    """

    rows_inserted = 0
    errors = 0

    for _, row in df_filtered.iterrows():
        try:
            cursor.execute(insert_sql, (
                str(row['metro_raw']),
                int(row['survey_year']),
                safe_float(row['median_household_income']),
                safe_float(row['per_capita_income']),
                row['population'],
                'Census ACS 5-Year'
            ))
            rows_inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logging.warning(f"Row insert failed: {e} | {row['metro_raw']} {row['survey_year']}")

    conn.commit()
    conn.close()
    logging.info(f"Staging load complete: {rows_inserted} rows inserted, {errors} errors")
    return rows_inserted


# ----------------------------------------------------------------
# Step 5: Load into prod.fact_income
# ----------------------------------------------------------------
def load_fact():
    logging.info("Loading into prod.fact_income...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE prod.fact_income;")
    conn.commit()
    logging.info("Truncated prod.fact_income")

    insert_sql = """
        INSERT INTO prod.fact_income
            (geo_id, survey_year, median_household_income,
             per_capita_income, population, data_source)
        SELECT
            g.geo_id,
            s.survey_year,
            s.median_household_income,
            s.per_capita_income,
            s.population,
            s.data_source
        FROM staging.income s
        JOIN prod.dim_geography g ON g.city_display = (
            SELECT city_display FROM (VALUES
                ('35620', 'New York'),
                ('31080', 'Los Angeles'),
                ('16980', 'Chicago'),
                ('19100', 'Dallas'),
                ('26420', 'Houston'),
                ('47900', 'Washington DC'),
                ('33100', 'Miami'),
                ('37980', 'Philadelphia'),
                ('12060', 'Atlanta'),
                ('38060', 'Phoenix'),
                ('14460', 'Boston'),
                ('40140', 'Riverside'),
                ('42660', 'Seattle'),
                ('33460', 'Minneapolis'),
                ('41740', 'San Diego'),
                ('45300', 'Tampa'),
                ('19740', 'Denver'),
                ('41180', 'St. Louis'),
                ('12580', 'Baltimore'),
                ('38900', 'Portland'),
                ('12420', 'Austin'),
                ('29820', 'Las Vegas'),
                ('41860', 'San Francisco'),
                ('16740', 'Charlotte'),
                ('34980', 'Nashville')
            ) AS cw(cbsa_code, city_display)
            -- Match via metro_raw name containing CBSA mapping
            -- We join through city_display matched in staging
            WHERE cw.city_display = (
                SELECT city_display FROM (VALUES
                    ('35620', 'New York'),
                    ('31080', 'Los Angeles'),
                    ('16980', 'Chicago'),
                    ('19100', 'Dallas'),
                    ('26420', 'Houston'),
                    ('47900', 'Washington DC'),
                    ('33100', 'Miami'),
                    ('37980', 'Philadelphia'),
                    ('12060', 'Atlanta'),
                    ('38060', 'Phoenix'),
                    ('14460', 'Boston'),
                    ('40140', 'Riverside'),
                    ('42660', 'Seattle'),
                    ('33460', 'Minneapolis'),
                    ('41740', 'San Diego'),
                    ('45300', 'Tampa'),
                    ('19740', 'Denver'),
                    ('41180', 'St. Louis'),
                    ('12580', 'Baltimore'),
                    ('38900', 'Portland'),
                    ('12420', 'Austin'),
                    ('29820', 'Las Vegas'),
                    ('41860', 'San Francisco'),
                    ('16740', 'Charlotte'),
                    ('34980', 'Nashville')
                ) AS cw2(cbsa_code2, city_display2)
                WHERE cw2.city_display2 = g.city_display
            )
        )
        WHERE s.median_household_income IS NOT NULL;
    """

    # Cleaner approach: Python-side join since staging already has city_display mapped
    # Use direct insert with city_display lookup
    cursor.execute("TRUNCATE TABLE prod.fact_income;")

    insert_direct = """
        INSERT INTO prod.fact_income
            (geo_id, survey_year, median_household_income,
             per_capita_income, population, data_source)
        SELECT
            g.geo_id,
            s.survey_year,
            s.median_household_income,
            s.per_capita_income,
            s.population,
            s.data_source
        FROM staging.income s
        JOIN prod.dim_geography g
            ON g.metro_name LIKE '%' + 
               CASE 
                   WHEN s.metro_raw LIKE '%New York%'        THEN 'New York'
                   WHEN s.metro_raw LIKE '%Los Angeles%'     THEN 'Los Angeles'
                   WHEN s.metro_raw LIKE '%Chicago%'         THEN 'Chicago'
                   WHEN s.metro_raw LIKE '%Dallas%'          THEN 'Dallas'
                   WHEN s.metro_raw LIKE '%Houston%'         THEN 'Houston'
                   WHEN s.metro_raw LIKE '%Washington%'      THEN 'Washington'
                   WHEN s.metro_raw LIKE '%Miami%'           THEN 'Miami'
                   WHEN s.metro_raw LIKE '%Philadelphia%'    THEN 'Philadelphia'
                   WHEN s.metro_raw LIKE '%Atlanta%'         THEN 'Atlanta'
                   WHEN s.metro_raw LIKE '%Phoenix%'         THEN 'Phoenix'
                   WHEN s.metro_raw LIKE '%Boston%'          THEN 'Boston'
                   WHEN s.metro_raw LIKE '%Riverside%'       THEN 'Riverside'
                   WHEN s.metro_raw LIKE '%Seattle%'         THEN 'Seattle'
                   WHEN s.metro_raw LIKE '%Minneapolis%'     THEN 'Minneapolis'
                   WHEN s.metro_raw LIKE '%San Diego%'       THEN 'San Diego'
                   WHEN s.metro_raw LIKE '%Tampa%'           THEN 'Tampa'
                   WHEN s.metro_raw LIKE '%Denver%'          THEN 'Denver'
                   WHEN s.metro_raw LIKE '%St. Louis%'       THEN 'St. Louis'
                   WHEN s.metro_raw LIKE '%Baltimore%'       THEN 'Baltimore'
                   WHEN s.metro_raw LIKE '%Portland%'        THEN 'Portland'
                   WHEN s.metro_raw LIKE '%Austin%'          THEN 'Austin'
                   WHEN s.metro_raw LIKE '%Las Vegas%'       THEN 'Las Vegas'
                   WHEN s.metro_raw LIKE '%San Francisco%'   THEN 'San Francisco'
                   WHEN s.metro_raw LIKE '%Charlotte%'       THEN 'Charlotte'
                   WHEN s.metro_raw LIKE '%Nashville%'       THEN 'Nashville'
               END + '%'
        WHERE s.median_household_income IS NOT NULL;
    """

    cursor.execute(insert_direct)
    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_income loaded: {rows} rows inserted")
    return rows


# ----------------------------------------------------------------
# Step 6: Validation
# ----------------------------------------------------------------
def validate():
    logging.info("Running post-load validation...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            g.city_display,
            COUNT(*)                        AS year_count,
            MIN(i.survey_year)              AS earliest_year,
            MAX(i.survey_year)              AS latest_year,
            MAX(i.median_household_income)  AS latest_income
        FROM prod.fact_income i
        JOIN prod.dim_geography g ON i.geo_id = g.geo_id
        GROUP BY g.city_display
        ORDER BY latest_income DESC;
    """)

    rows = cursor.fetchall()
    print("\n--- Validation: fact_income by city ---")
    print(f"{'City':<20} {'Years':>6} {'From':>6} {'To':>6} {'Latest Income':>15}")
    print("-" * 60)
    for row in rows:
        print(f"{row.city_display:<20} {row.year_count:>6} {row.earliest_year:>6} {row.latest_year:>6} ${row.latest_income:>14,.0f}")

    cursor.execute("SELECT COUNT(*) FROM prod.fact_income WHERE median_household_income IS NULL;")
    null_count = cursor.fetchone()[0]
    logging.info(f"NULL income values in fact_income: {null_count}")

    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("ETL START: Census ACS Income")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)

    if CENSUS_API_KEY == "YOUR_CENSUS_API_KEY_HERE":
        logging.error(
            "Census API key not set.\n"
            "  1. Get a free key at: https://api.census.gov/data/key_signup.html\n"
            "  2. Open this script and replace YOUR_CENSUS_API_KEY_HERE with your key\n"
            "  3. Re-run the script"
        )
        sys.exit(1)

    try:
        df_raw      = download_acs()
        df_clean    = parse_acs(df_raw)
        load_staging(df_clean)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: Census ACS Income")

    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
