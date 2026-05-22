"""
etl_zillow_zhvi.py
ETL script: Zillow Home Value Index (ZHVI)
Extracts median home price data for the top 25 metros, loads into:
  staging.home_prices  ->  prod.fact_home_prices

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
        logging.FileHandler(LOG_DIR / "etl_zillow_zhvi.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------
# ZHVI download URLs
# If all fail, download manually from https://www.zillow.com/research/data/
# HOME VALUES -> ZHVI All Homes (SFR, Condo/Co-op) -> Metro -> Download
# Save as data/Metro_zhvi.csv
# ----------------------------------------------------------------
ZHVI_URLS = [
    "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_sm_sa_month.csv",
]

MANUAL_CSV = BASE_DIR / "data" / "Metro_zhvi.csv"

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


def download_zhvi():
    from io import StringIO
    if MANUAL_CSV.exists():
        logging.info(f"Loading ZHVI from manual CSV: {MANUAL_CSV}")
        df = pd.read_csv(MANUAL_CSV)
        logging.info(f"Loaded ZHVI: {df.shape[0]} rows, {df.shape[1]} columns")
        return df

    for url in ZHVI_URLS:
        logging.info(f"Trying ZHVI URL: {url}")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))
            logging.info(f"Downloaded ZHVI: {df.shape[0]} rows, {df.shape[1]} columns")
            return df
        except Exception as e:
            logging.warning(f"URL failed: {url} | {e}")
            continue

    logging.error(
        "All ZHVI URLs failed.\n"
        "Manual fix:\n"
        "  1. Go to https://www.zillow.com/research/data/\n"
        "  2. HOME VALUES -> ZHVI All Homes -> Metro -> Download CSV\n"
        f"  3. Save to: {MANUAL_CSV}\n"
        "  4. Re-run the script."
    )
    raise FileNotFoundError("Could not download ZHVI CSV. See log for instructions.")


def parse_zhvi(df):
    logging.info("Parsing ZHVI data...")
    logging.info(f"Sample Zillow metro names:\n{list(df['RegionName'].unique()[:30])}")

    df_filtered = df[df['RegionName'].isin(METRO_CROSSWALK.keys())].copy()
    logging.info(f"Matched {df_filtered['RegionName'].nunique()} of 25 metros")

    matched = set(df_filtered['RegionName'].unique())
    missing = set(METRO_CROSSWALK.keys()) - matched
    if missing:
        logging.warning(f"Missing metros (update crosswalk): {missing}")

    df_filtered['city_display'] = df_filtered['RegionName'].map(METRO_CROSSWALK)

    meta_cols = ['RegionID', 'SizeRank', 'RegionName', 'RegionType',
                 'StateName', 'State', 'Metro', 'city_display']
    meta_cols = [c for c in meta_cols if c in df_filtered.columns]
    date_cols = [c for c in df_filtered.columns if c not in meta_cols]

    df_long = df_filtered.melt(
        id_vars=meta_cols,
        value_vars=date_cols,
        var_name='report_date_str',
        value_name='median_home_price'
    )

    df_long['report_date'] = pd.to_datetime(df_long['report_date_str'], errors='coerce')
    df_long = df_long.dropna(subset=['report_date', 'median_home_price'])
    df_long['median_home_price'] = df_long['median_home_price'].apply(safe_float)
    df_long = df_long.dropna(subset=['median_home_price'])
    df_long = df_long[df_long['report_date'] >= '2015-01-01']

    logging.info(f"Parsed {len(df_long)} home price records after filtering")
    return df_long


def load_staging(df_long):
    logging.info("Loading into staging.home_prices...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.home_prices;")
    conn.commit()

    insert_sql = """
        INSERT INTO staging.home_prices
            (metro_raw, report_date, median_home_price, home_type, data_source)
        VALUES (?, ?, ?, ?, ?)
    """
    rows_inserted = 0
    errors = 0

    for _, row in df_long.iterrows():
        try:
            cursor.execute(insert_sql, (
                str(row['RegionName']),
                row['report_date'].date(),
                safe_float(row['median_home_price']),
                'All Homes',
                'Zillow ZHVI'
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
    logging.info("Loading into prod.fact_home_prices...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE prod.fact_home_prices;")
    conn.commit()

    cursor.execute("""
        INSERT INTO prod.fact_home_prices
            (geo_id, date_id, median_home_price, home_type, data_source)
        SELECT
            g.geo_id,
            CAST(FORMAT(s.report_date, 'yyyyMMdd') AS INT) AS date_id,
            s.median_home_price,
            s.home_type,
            s.data_source
        FROM staging.home_prices s
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
        WHERE s.median_home_price IS NOT NULL;
    """)

    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_home_prices: {rows} rows")
    return rows


def validate():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT g.city_display, COUNT(*) AS row_count,
               MIN(d.full_date) AS earliest, MAX(d.full_date) AS latest,
               AVG(hp.median_home_price) AS avg_home_price
        FROM prod.fact_home_prices hp
        JOIN prod.dim_geography g ON hp.geo_id  = g.geo_id
        JOIN prod.dim_date d      ON hp.date_id = d.date_id
        WHERE hp.home_type = 'All Homes'
        GROUP BY g.city_display
        ORDER BY avg_home_price DESC;
    """)
    rows = cursor.fetchall()
    print("\n--- Validation: fact_home_prices by city ---")
    print(f"{'City':<20} {'Rows':>6} {'Earliest':<12} {'Latest':<12} {'Avg Price':>12}")
    print("-" * 68)
    for row in rows:
        print(f"{row.city_display:<20} {row.row_count:>6} {str(row.earliest):<12} {str(row.latest):<12} ${row.avg_home_price:>11,.0f}")
    cursor.execute("SELECT COUNT(*) FROM prod.fact_home_prices WHERE median_home_price IS NULL;")
    logging.info(f"NULL home price values: {cursor.fetchone()[0]}")
    conn.close()


def main():
    logging.info("=" * 60)
    logging.info("ETL START: Zillow ZHVI")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)
    try:
        df_raw   = download_zhvi()
        df_clean = parse_zhvi(df_raw)
        load_staging(df_clean)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: Zillow ZHVI")
    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
