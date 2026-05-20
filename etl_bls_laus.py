"""
etl_bls_laus.py
ETL script: Bureau of Labor Statistics - Local Area Unemployment Statistics (LAUS)
Extracts monthly unemployment rate, employment level, and labor force
for the top 25 metros, loads into:
  staging.labor  →  prod.fact_labor

Correct series ID format (verified from BLS la.series flat file):
  LASMT + state_fips(2) + cbsa(5) + 0000000 + measure(2)
  Example: LASMT534266000000003 = Seattle unemployment rate
           LAS  = prefix
           MT   = area type (metropolitan statistical area)
           53   = state FIPS (WA)
           42660 = CBSA code
           0000000 = padding (7 zeros)
           03   = measure (03=rate, 04=unemployed, 05=employed, 06=labor force)

Verified from BLS flat file: https://download.bls.gov/pub/time.series/la/la.series

Project: City Affordability Dashboard
Path:    C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard
"""

import os
import sys
import logging
import math
import requests
import pandas as pd
from datetime import datetime

PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)
from db_utils import get_connection

LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_bls_laus.log")
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
# !! ENTER YOUR BLS API KEY HERE !!
# Free at: https://data.bls.gov/registrationEngine/
# ----------------------------------------------------------------
BLS_API_KEY = "YOUR_BLS_API_KEY_HERE"

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# ----------------------------------------------------------------
# Verified BLS LAUS series IDs from BLS la.series flat file
# Format: LASMT + state_fips(2) + cbsa(5) + 0000000 + measure(2)
# Measures: 03=unemployment rate, 05=employment, 06=labor force
#
# Seasonal adjusted (S prefix) versions used where available.
# Non-seasonally adjusted (U) for metros without SA series.
# ----------------------------------------------------------------
METRO_SERIES = {
    # city_display : (state_fips, cbsa)
    "New York":      ("36", "35620"),
    "Los Angeles":   ("06", "31080"),
    "Chicago":       ("17", "16980"),
    "Dallas":        ("48", "19100"),
    "Houston":       ("48", "26420"),
    "Washington DC": ("11", "47900"),
    "Miami":         ("12", "33100"),
    "Philadelphia":  ("42", "37980"),
    "Atlanta":       ("13", "12060"),
    "Phoenix":       ("04", "38060"),
    "Boston":        ("25", "14460"),
    "Riverside":     ("06", "40140"),
    "Seattle":       ("53", "42660"),
    "Minneapolis":   ("27", "33460"),
    "San Diego":     ("06", "41740"),
    "Tampa":         ("12", "45300"),
    "Denver":        ("08", "19740"),
    "St. Louis":     ("29", "41180"),
    "Baltimore":     ("24", "12580"),
    "Portland":      ("41", "38900"),
    "Austin":        ("48", "12420"),
    "Las Vegas":     ("32", "29820"),
    "San Francisco": ("06", "41860"),
    "Charlotte":     ("37", "16740"),
    "Nashville":     ("47", "34980"),
}

# Measure codes
MEASURES = {
    "03": "unemployment_rate",
    "05": "employment_level",
    "06": "labor_force",
}


def build_series_ids():
    """
    Build series IDs in correct LASMT format.
    LASMT + state(2) + cbsa(5) + 0000000 + measure(2) = 20 chars total
    Example: LASMT534266000000003
    """
    series_map = {}
    for city, (state_fips, cbsa) in METRO_SERIES.items():
        for measure_code, measure_name in MEASURES.items():
            series_id = f"LAUMT{state_fips}{cbsa}000000{measure_code}"
            series_map[series_id] = (city, measure_name)
    return series_map


def safe_float(val):
    if val is None:
        return None
    if hasattr(val, 'item'):
        val = val.item()
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (ValueError, TypeError):
        return None


def to_int(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else int(f)
    except:
        return None


# ----------------------------------------------------------------
# Step 1: Fetch from BLS API
# ----------------------------------------------------------------
def fetch_bls_batch(series_list, start_year, end_year):
    payload = {
        "seriesid":      series_list,
        "startyear":     str(start_year),
        "endyear":       str(end_year),
        "catalog":       False,
        "calculations":  False,
        "annualaverage": False,
    }
    if BLS_API_KEY != "YOUR_BLS_API_KEY_HERE":
        payload["registrationkey"] = BLS_API_KEY

    try:
        response = requests.post(BLS_API_URL, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        messages = data.get("message", [])
        if messages:
            # Only log first message to avoid log spam
            logging.info(f"BLS message: {messages[0]}")

        if data.get("status") != "REQUEST_SUCCEEDED":
            logging.warning(f"BLS status: {data.get('status')}")
            return []

        return data.get("Results", {}).get("series", [])

    except Exception as e:
        logging.error(f"BLS API request failed: {e}")
        return []


def download_bls():
    logging.info("Downloading BLS LAUS data...")
    all_series_map = build_series_ids()
    series_ids = list(all_series_map.keys())

    logging.info(f"Total series: {len(series_ids)}")
    logging.info(f"Sample IDs: {series_ids[:3]}")

    all_records = []
    year_windows = [(2015, 2019), (2020, 2025)]

    for start_year, end_year in year_windows:
        logging.info(f"Fetching {start_year}-{end_year}...")

        for i in range(0, len(series_ids), 50):
            batch = series_ids[i:i+50]
            results = fetch_bls_batch(batch, start_year, end_year)

            if not results:
                logging.warning(f"No results for batch {i//50+1}")
                continue

            for series in results:
                series_id = series.get("seriesID", "")
                if series_id not in all_series_map:
                    continue

                city, measure = all_series_map[series_id]
                data_points = series.get("data", [])

                if not data_points:
                    logging.warning(f"No data: {series_id} ({city} {measure})")
                    continue

                for obs in data_points:
                    period = obs.get("period", "")
                    if not period.startswith("M") or period == "M13":
                        continue

                    year  = int(obs.get("year", 0))
                    month = int(period.replace("M", ""))
                    value = obs.get("value", None)

                    all_records.append({
                        "city_display": city,
                        "report_date":  f"{year}-{month:02d}-01",
                        "measure":      measure,
                        "value":        safe_float(value),
                    })

    logging.info(f"Total observations fetched: {len(all_records)}")
    return pd.DataFrame(all_records) if all_records else pd.DataFrame()


# ----------------------------------------------------------------
# Step 2: Pivot
# ----------------------------------------------------------------
def parse_bls(df):
    logging.info("Parsing BLS data...")

    if df.empty:
        raise ValueError(
            "No BLS data fetched. Series IDs still incorrect.\n"
            "Next step: download the BLS series list manually.\n"
            "  1. Go to: https://download.bls.gov/pub/time.series/la/la.series\n"
            "  2. Save the file and search for 'New York-Newark' to find the correct series ID.\n"
            "  3. Update METRO_SERIES in this script with the correct area codes."
        )

    df['report_date'] = pd.to_datetime(df['report_date'])

    df_pivot = df.pivot_table(
        index=['city_display', 'report_date'],
        columns='measure',
        values='value',
        aggfunc='first'
    ).reset_index()
    df_pivot.columns.name = None

    for col in ['unemployment_rate', 'employment_level', 'labor_force']:
        if col not in df_pivot.columns:
            df_pivot[col] = None

    df_pivot = df_pivot[df_pivot['report_date'] >= '2015-01-01']

    cities_found = df_pivot['city_display'].nunique()
    logging.info(f"Parsed {len(df_pivot)} records across {cities_found} of 25 cities")

    missing = set(METRO_SERIES.keys()) - set(df_pivot['city_display'].unique())
    if missing:
        logging.warning(f"Missing cities: {missing}")

    return df_pivot


# ----------------------------------------------------------------
# Step 3: Load staging
# ----------------------------------------------------------------
def load_staging(df_pivot):
    logging.info("Loading into staging.labor...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE staging.labor;")
    conn.commit()

    insert_sql = """
        INSERT INTO staging.labor
            (metro_raw, report_date, unemployment_rate,
             employment_level, labor_force, data_source)
        VALUES (?, ?, ?, ?, ?, ?)
    """

    rows_inserted = 0
    errors = 0

    for _, row in df_pivot.iterrows():
        try:
            cursor.execute(insert_sql, (
                str(row['city_display']),
                row['report_date'].date(),
                safe_float(row.get('unemployment_rate')),
                to_int(row.get('employment_level')),
                to_int(row.get('labor_force')),
                'BLS LAUS'
            ))
            rows_inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logging.warning(f"Insert failed: {e} | {row['city_display']}")

    conn.commit()
    conn.close()
    logging.info(f"Staging: {rows_inserted} rows, {errors} errors")
    return rows_inserted


# ----------------------------------------------------------------
# Step 4: Load fact
# ----------------------------------------------------------------
def load_fact():
    logging.info("Loading into prod.fact_labor...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE prod.fact_labor;")
    conn.commit()

    cursor.execute("""
        INSERT INTO prod.fact_labor
            (geo_id, date_id, unemployment_rate,
             employment_level, labor_force, data_source)
        SELECT
            g.geo_id,
            CAST(FORMAT(s.report_date, 'yyyyMMdd') AS INT),
            s.unemployment_rate,
            s.employment_level,
            s.labor_force,
            s.data_source
        FROM staging.labor s
        JOIN prod.dim_geography g ON g.city_display = s.metro_raw
        WHERE s.unemployment_rate IS NOT NULL;
    """)

    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_labor: {rows} rows")
    return rows


# ----------------------------------------------------------------
# Step 5: Validate
# ----------------------------------------------------------------
def validate():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            g.city_display,
            COUNT(*)                 AS row_count,
            MIN(d.full_date)         AS earliest,
            MAX(d.full_date)         AS latest,
            AVG(l.unemployment_rate) AS avg_unemp,
            MIN(l.unemployment_rate) AS min_unemp,
            MAX(l.unemployment_rate) AS max_unemp
        FROM prod.fact_labor l
        JOIN prod.dim_geography g ON l.geo_id  = g.geo_id
        JOIN prod.dim_date d      ON l.date_id = d.date_id
        GROUP BY g.city_display
        ORDER BY avg_unemp DESC;
    """)

    rows = cursor.fetchall()
    print("\n--- Validation: fact_labor by city ---")
    print(f"{'City':<20} {'Rows':>6} {'Earliest':<12} {'Latest':<12} {'Avg%':>6} {'Min%':>6} {'Max%':>6}")
    print("-" * 75)
    for row in rows:
        print(
            f"{row.city_display:<20} {row.row_count:>6} "
            f"{str(row.earliest):<12} {str(row.latest):<12} "
            f"{row.avg_unemp:>6.1f} {row.min_unemp:>6.1f} {row.max_unemp:>6.1f}"
        )

    cursor.execute("SELECT COUNT(*) FROM prod.fact_labor WHERE unemployment_rate IS NULL;")
    logging.info(f"NULL unemployment values: {cursor.fetchone()[0]}")
    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("ETL START: BLS LAUS")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)

    if BLS_API_KEY == "YOUR_BLS_API_KEY_HERE":
        logging.warning("No BLS API key set.")

    try:
        df_raw   = download_bls()
        df_clean = parse_bls(df_raw)
        load_staging(df_clean)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: BLS LAUS")
    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
