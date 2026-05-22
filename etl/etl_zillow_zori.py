"""
etl_zillow_zori.py
ETL script: Zillow Observed Rent Index (ZORI)
Extracts rent data for the top 25 metros, loads into:
  staging.rent  ->  prod.fact_rent

Source: https://www.zillow.com/research/data/
"""

import os
import sys
import logging
import math
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime

# ----------------------------------------------------------------
# Project root and paths — all relative, no hardcoded local paths
# ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(BASE_DIR))
from db_utils import get_connection

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "etl_zillow_zori.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------
# ZORI download URLs (Zillow changes these periodically)
# If all fail, download manually from https://www.zillow.com/research/data/
# RENTALS -> ZORI -> Geography: Metro -> Download CSV
# Save as data/Metro_zori.csv and set MANUAL_CSV below
# ----------------------------------------------------------------
ZORI_URLS = [
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv",
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_ZORI_AllHomesPlusMultifamily_Smoothed.csv",
    "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_sm_month.csv",
]

MANUAL_CSV = BASE_DIR / "data" / "Metro_zori.csv"

# ----------------------------------------------------------------
# Metro crosswalk — verified against Zillow RegionName values
# ----------------------------------------------------------------
METRO_CROSSWALK = {
    "New York, NY":         "New York",
    "Los Angeles, CA":      "Los Angeles",
    "Chicago, IL":          "Chicago",
    "Dallas, TX":           "Dallas",
    "Houston, TX":          "Houston",
    "Washington, DC":       "Washington DC",
    "Miami, FL":            "Miami",
    "Philadelphia, PA":     "Philadelphia",
    "Atlanta, GA":          "Atlanta",
    "Phoenix, AZ":          "Phoenix",
    "Boston, MA":           "Boston",
    "Riverside, CA":        "Riverside",
    "Seattle, WA":          "Seattle",
    "Minneapolis, MN":      "Minneapolis",
    "San Diego, CA":        "San Diego",
    "Tampa, FL":            "Tampa",
    "Denver, CO":           "Denver",
    "St. Louis, MO":        "St. Louis",
    "Baltimore, MD":        "Baltimore",
    "Portland, OR":         "Portland",
    "Austin, TX":           "Austin",
    "Las Vegas, NV":        "Las Vegas",
    "San Francisco, CA":    "San Francisco",
    "Charlotte, NC":        "Charlotte",
    "Nashville, TN":        "Nashville",
}


def safe_float(val):
    if val is None:
        return None
    if hasattr(val, 'item'):
        val = val.item()
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (ValueError, TypeError):
        return None


def download_zori():
    from io import StringIO
    if MANUAL_CSV.exists():
        logging.info(f"Loading ZORI from manual CSV: {MANUAL_CSV}")
        df = pd.read_csv(MANUAL_CSV)
        logging.info(f"Loaded ZORI: {df.shape[0]} rows, {df.shape[1]} columns")
        return df

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

    logging.error(
        "All ZORI URLs failed.\n"
        "Manual fix:\n"
        "  1. Go to https://www.zillow.com/research/data/\n"
        "  2. RENTALS -> ZORI -> Geography: Metro -> Download CSV\n"
        f"  3. Save to: {MANUAL_CSV}\n"
        "  4. Re-run the script."
    )
    raise FileNotFoundError("Could not download ZORI CSV. See log for instructions.")


def parse_zori(df):
    logging.info("Parsing ZORI data...")
    logging.info(f"Sample Zillow metro names:\n{list(df['RegionName'].unique()[:30])}")

    df_filtered = df[df['RegionName'].isin(METRO_CROSSWALK.keys())].copy()
    logging.info(f"Matched {df_filtered['RegionName'].nunique()} of 25 metros")

    matched = set(df_filtered['RegionName'].unique())
    missing = set(METRO_CROSSWALK.keys()) - matched
    if missing:
        logging.warning(f"Missing metros (update crosswalk): {missing}")

    df_filtered['city_display'] = df_filtered['RegionName'].map(METRO_CROSSWALK)

    meta_cols = ['RegionID', 'SizeRank', 'RegionName', 'RegionType',
                 'StateName', 'city_display']
    meta_cols = [c for c in meta_cols if c in df_filtered.columns]
    date_cols = [c for c in df_filtered.columns if c not in meta_cols]

    df_long = df_filtered.melt(
        id_vars=meta_cols,
        value_vars=date_cols,
        var_name='report_date_str',
        value_name='monthly_rent'
    )

    df_long['report_date'] = pd.to_datetime(df_long['report_date_str'], errors='coerce')
    df_long = df_long.dropna(subset=['report_date', 'monthly_rent'])
    df_long['monthly_rent'] = df_long['monthly_rent'].apply(safe_float)
    df_long = df_long.dropna(subset=['monthly_rent'])
    df_long = df_long[df_long['report_date'] >= '2015-01-01']

    logging.info(f"Parsed {len(df_long)} rent records after filtering")
    return df_long


def load_staging(df_long):
    logging.info("Loading into staging.rent...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.rent;")
    conn.commit()

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
            if errors <= 5:
                logging.warning(f"Row insert failed: {e}")

    conn.commit()
    conn.close()
    logging.info(f"Staging: {rows_inserted} rows, {errors} errors")
    return rows_inserted


def load_fact():
    logging.info("Loading into prod.fact_rent...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE prod.fact_rent;")
    conn.commit()

    cursor.execute("""
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
                    ('New York, NY','New York'),('Los Angeles, CA','Los Angeles'),
                    ('Chicago, IL','Chicago'),('Dallas, TX','Dallas'),
                    ('Houston, TX','Houston'),('Washington, DC','Washington DC'),
                    ('Miami, FL','Miami'),('Philadelphia, PA','Philadelphia'),
                    ('Atlanta, GA','Atlanta'),('Phoenix, AZ','Phoenix'),
                    ('Boston, MA','Boston'),('Riverside, CA','Riverside'),
                    ('Seattle, WA','Seattle'),('Minneapolis, MN','Minneapolis'),
                    ('San Diego, CA','San Diego'),('Tampa, FL','Tampa'),
                    ('Denver, CO','Denver'),('St. Louis, MO','St. Louis'),
                    ('Baltimore, MD','Baltimore'),('Portland, OR','Portland'),
                    ('Austin, TX','Austin'),('Las Vegas, NV','Las Vegas'),
                    ('San Francisco, CA','San Francisco'),('Charlotte, NC','Charlotte'),
                    ('Nashville, TN','Nashville')
                ) AS cw(zillow_name, city_display)
                WHERE cw.zillow_name = s.metro_raw
            )
        WHERE s.monthly_rent IS NOT NULL;
    """)

    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_rent: {rows} rows")
    return rows


def validate():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT g.city_display, COUNT(*) AS rows,
               MIN(r.full_date) AS earliest, MAX(r.full_date) AS latest,
               AVG(r.monthly_rent) AS avg_rent
        FROM prod.vw_affordability_metrics r
        JOIN prod.dim_geography g ON r.geo_id = g.geo_id
        WHERE r.bedroom_type = 'All Homes'
        GROUP BY g.city_display ORDER BY g.city_display;
    """)
    rows = cursor.fetchall()
    print("\n--- Validation: fact_rent by city ---")
    print(f"{'City':<20} {'Rows':>6} {'Earliest':<12} {'Latest':<12} {'Avg Rent':>10}")
    print("-" * 65)
    for row in rows:
        print(f"{row.city_display:<20} {row.rows:>6} {str(row.earliest):<12} {str(row.latest):<12} ${row.avg_rent:>9,.0f}")
    cursor.execute("SELECT COUNT(*) FROM prod.fact_rent WHERE monthly_rent IS NULL;")
    logging.info(f"NULL rent values: {cursor.fetchone()[0]}")
    conn.close()


def main():
    logging.info("=" * 60)
    logging.info("ETL START: Zillow ZORI")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)
    try:
        df_raw   = download_zori()
        df_clean = parse_zori(df_raw)
        load_staging(df_clean)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: Zillow ZORI")
    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
