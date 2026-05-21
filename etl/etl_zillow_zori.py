"""
etl_zillow_zori.py
ETL script: Zillow Observed Rent Index (ZORI)
Extracts rent data for the top 25 metros, loads into:
  staging.rent  →  prod.fact_rent

Source: https://www.zillow.com/research/data/
File:   Zip_ZORI_AllHomesPlusMultifamily_Smoothed.csv  (metro-level)

Project: City Affordability Dashboard
Path:    C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard
"""

import os
import sys
import logging
import pyodbc
import pandas as pd
import requests
from datetime import datetime

# ----------------------------------------------------------------
# Add project root to path so db_utils is importable
# ----------------------------------------------------------------
PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)
from db_utils import get_connection

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_zillow_zori.log")
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
# Zillow ZORI download URLs
# NOTE: Zillow changes these paths frequently.
# Try each URL in order. If all fail, download manually:
#   1. Go to https://www.zillow.com/research/data/
#   2. Under RENTALS -> ZORI -> Geography: Metro -> Download CSV
#   3. Save as Metro_zori.csv in your project folder
#   4. Set MANUAL_CSV below to that path
# ----------------------------------------------------------------
ZORI_URLS = [
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv",
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_ZORI_AllHomesPlusMultifamily_Smoothed.csv",
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_sm_month.csv",
]

# If you downloaded manually, set this path. Otherwise leave as None.
MANUAL_CSV = None
MANUAL_CSV = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard\Metro_zori.csv"

# ----------------------------------------------------------------
# Canonical metro crosswalk
# Maps Zillow metro names → our dim_geography city_display names
# Run print(df['RegionName'].unique()) after download to verify
# ----------------------------------------------------------------
METRO_CROSSWALK = {
    "New York, NY":                         "New York",
    "Los Angeles, CA":                      "Los Angeles",
    "Chicago, IL":                          "Chicago",
    "Dallas, TX":                           "Dallas",
    "Houston, TX":                          "Houston",
    "Washington, DC":                       "Washington DC",
    "Miami, FL":                            "Miami",
    "Philadelphia, PA":                     "Philadelphia",
    "Atlanta, GA":                          "Atlanta",
    "Phoenix, AZ":                          "Phoenix",
    "Boston, MA":                           "Boston",
    "Riverside, CA":                        "Riverside",
    "Seattle, WA":                          "Seattle",
    "Minneapolis, MN":                      "Minneapolis",
    "San Diego, CA":                        "San Diego",
    "Tampa, FL":                            "Tampa",
    "Denver, CO":                           "Denver",
    "St. Louis, MO":                        "St. Louis",
    "Baltimore, MD":                        "Baltimore",
    "Portland, OR":                         "Portland",
    "Austin, TX":                           "Austin",
    "Las Vegas, NV":                        "Las Vegas",
    "San Francisco, CA":                    "San Francisco",
    "Charlotte, NC":                        "Charlotte",
    "Nashville, TN":                        "Nashville",
}

# ----------------------------------------------------------------
# Helper: safe float conversion (mirrors COT pipeline pattern)
# ----------------------------------------------------------------
def safe_float(val):
    if val is None:
        return None
    if hasattr(val, 'item'):
        val = val.item()
    try:
        f = float(val)
        import math
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------
# Step 1: Download ZORI CSV from Zillow
# ----------------------------------------------------------------
def download_zori():
    from io import StringIO

    # Option 1: Manual CSV override
    if MANUAL_CSV and os.path.exists(MANUAL_CSV):
        logging.info(f"Loading ZORI from manual CSV: {MANUAL_CSV}")
        df = pd.read_csv(MANUAL_CSV)
        logging.info(f"Loaded ZORI: {df.shape[0]} rows, {df.shape[1]} columns")
        return df

    # Option 2: Try each URL in order
    for url in ZORI_URLS:
        logging.info(f"Trying ZORI URL: {url}")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))
            logging.info(f"Downloaded ZORI: {df.shape[0]} rows, {df.shape[1]} columns")
            return df
        except Exception as e:
            logging.warning(f"URL failed: {url} | {e}")
            continue

    # All URLs failed -- instruct manual download
    logging.error(
        "All ZORI URLs failed. Zillow has changed their file paths.\n"
        "Manual fix:\n"
        "  1. Go to https://www.zillow.com/research/data/\n"
        "  2. Under RENTALS -> ZORI -> Geography: Metro -> Download CSV\n"
        f"  3. Save the file to: {PROJECT_DIR}\\Metro_zori.csv\n"
        "  4. Uncomment and set MANUAL_CSV in this script to that path and re-run."
    )
    raise FileNotFoundError("Could not download ZORI CSV. See log for manual download instructions.")


# ----------------------------------------------------------------
# Step 2: Parse and filter to top 25 metros
# ----------------------------------------------------------------
def parse_zori(df):
    logging.info("Parsing ZORI data...")

    # Diagnostic: print all metro names so crosswalk can be verified
    logging.info(f"Sample Zillow metro names:\n{df['RegionName'].unique()[:30]}")

    # Filter to our 25 metros only
    df_filtered = df[df['RegionName'].isin(METRO_CROSSWALK.keys())].copy()
    logging.info(f"Matched {df_filtered['RegionName'].nunique()} of 25 metros")

    # Warn if any metros are missing
    matched = set(df_filtered['RegionName'].unique())
    expected = set(METRO_CROSSWALK.keys())
    missing = expected - matched
    if missing:
        logging.warning(f"Missing metros (update crosswalk): {missing}")

    # Map to canonical city display name
    df_filtered['city_display'] = df_filtered['RegionName'].map(METRO_CROSSWALK)

    # Melt date columns wide → long
    # Date columns are everything after the metadata columns
    meta_cols = ['RegionID', 'SizeRank', 'RegionName', 'RegionType',
                 'StateName', 'city_display']
    # Keep only columns that exist in this file
    meta_cols = [c for c in meta_cols if c in df_filtered.columns]
    date_cols = [c for c in df_filtered.columns if c not in meta_cols]

    df_long = df_filtered.melt(
        id_vars=meta_cols,
        value_vars=date_cols,
        var_name='report_date_str',
        value_name='monthly_rent'
    )

    # Parse dates
    df_long['report_date'] = pd.to_datetime(df_long['report_date_str'], errors='coerce')
    df_long = df_long.dropna(subset=['report_date', 'monthly_rent'])
    df_long['monthly_rent'] = df_long['monthly_rent'].apply(safe_float)
    df_long = df_long.dropna(subset=['monthly_rent'])

    # Filter to 2015 onwards
    df_long = df_long[df_long['report_date'] >= '2015-01-01']

    logging.info(f"Parsed {len(df_long)} rent records after filtering")
    return df_long


# ----------------------------------------------------------------
# Step 3: Load into staging.rent
# ----------------------------------------------------------------
def load_staging(df_long):
    logging.info("Loading into staging.rent...")
    conn = get_connection()
    cursor = conn.cursor()

    # TRUNCATE staging first (COT pattern)
    cursor.execute("TRUNCATE TABLE staging.rent;")
    conn.commit()
    logging.info("Truncated staging.rent")

    insert_sql = """
        INSERT INTO staging.rent
            (metro_raw, report_date, monthly_rent, bedroom_type, data_source)
        VALUES (?, ?, ?, ?, ?)
    """

    rows_inserted = 0
    errors = 0

    for _, row in df_long.iterrows():
        try:
            cursor.execute(insert_sql, (
                str(row['RegionName']),
                row['report_date'].date(),
                safe_float(row['monthly_rent']),
                'All Homes',
                'Zillow ZORI'
            ))
            rows_inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:  # log first 5 errors only
                logging.warning(f"Row insert failed: {e} | row: {row['RegionName']} {row['report_date']}")

    conn.commit()
    conn.close()
    logging.info(f"Staging load complete: {rows_inserted} rows inserted, {errors} errors")
    return rows_inserted


# ----------------------------------------------------------------
# Step 4: Load into prod.fact_rent
# ----------------------------------------------------------------
def load_fact():
    logging.info("Loading into prod.fact_rent...")
    conn = get_connection()
    cursor = conn.cursor()

    # TRUNCATE fact table first
    cursor.execute("TRUNCATE TABLE prod.fact_rent;")
    conn.commit()
    logging.info("Truncated prod.fact_rent")

    insert_sql = """
        INSERT INTO prod.fact_rent
            (geo_id, date_id, monthly_rent, bedroom_type, data_source)
        SELECT
            g.geo_id,
            CAST(FORMAT(s.report_date, 'yyyyMMdd') AS INT) AS date_id,
            s.monthly_rent,
            s.bedroom_type,
            s.data_source
        FROM staging.rent s
        JOIN prod.dim_geography g
            ON g.city_display = (
                SELECT city_display FROM (VALUES
                    ('New York, NY',                         'New York'),
                    ('Los Angeles-Long Beach-Anaheim, CA',   'Los Angeles'),
                    ('Chicago, IL',                          'Chicago'),
                    ('Dallas-Fort Worth, TX',                'Dallas'),
                    ('Houston, TX',                          'Houston'),
                    ('Washington, DC',                       'Washington DC'),
                    ('Miami-Fort Lauderdale, FL',            'Miami'),
                    ('Philadelphia, PA',                     'Philadelphia'),
                    ('Atlanta, GA',                          'Atlanta'),
                    ('Phoenix, AZ',                          'Phoenix'),
                    ('Boston, MA',                           'Boston'),
                    ('Riverside, CA',                        'Riverside'),
                    ('Seattle, WA',                          'Seattle'),
                    ('Minneapolis-St Paul, MN',              'Minneapolis'),
                    ('San Diego, CA',                        'San Diego'),
                    ('Tampa, FL',                            'Tampa'),
                    ('Denver, CO',                           'Denver'),
                    ('St. Louis, MO',                        'St. Louis'),
                    ('Baltimore, MD',                        'Baltimore'),
                    ('Portland, OR',                         'Portland'),
                    ('Austin, TX',                           'Austin'),
                    ('Las Vegas, NV',                        'Las Vegas'),
                    ('San Francisco, CA',                    'San Francisco'),
                    ('Charlotte, NC',                        'Charlotte'),
                    ('Nashville, TN',                        'Nashville')
                ) AS cw(zillow_name, city_display)
                WHERE cw.zillow_name = s.metro_raw
            )
        WHERE s.monthly_rent IS NOT NULL;
    """

    cursor.execute(insert_sql)
    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_rent loaded: {rows} rows inserted")
    return rows


# ----------------------------------------------------------------
# Step 5: Validation
# ----------------------------------------------------------------
def validate():
    logging.info("Running post-load validation...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            g.city_display,
            COUNT(*) AS row_count,
            MIN(r.full_date) AS earliest,
            MAX(r.full_date) AS latest,
            AVG(r.monthly_rent) AS avg_rent
        FROM prod.vw_affordability_metrics r
        JOIN prod.dim_geography g ON r.geo_id = g.geo_id
        WHERE r.bedroom_type = 'All Homes'
        GROUP BY g.city_display
        ORDER BY g.city_display;
    """)

    rows = cursor.fetchall()
    print("\n--- Validation: fact_rent by city ---")
    print(f"{'City':<20} {'Rows':>6} {'Earliest':<12} {'Latest':<12} {'Avg Rent':>10}")
    print("-" * 65)
    for row in rows:
        print(f"{row.city_display:<20} {row.row_count:>6} {str(row.earliest):<12} {str(row.latest):<12} ${row.avg_rent:>9,.0f}")

    cursor.execute("SELECT COUNT(*) FROM prod.fact_rent WHERE monthly_rent IS NULL;")
    null_count = cursor.fetchone()[0]
    logging.info(f"NULL rent values in fact_rent: {null_count}")

    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("ETL START: Zillow ZORI")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)

    try:
        # Download
        df_raw = download_zori()

        # Parse
        df_clean = parse_zori(df_raw)

        # Load staging
        load_staging(df_clean)

        # Load fact
        load_fact()

        # Validate
        validate()

        logging.info("ETL COMPLETE: Zillow ZORI")

    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
