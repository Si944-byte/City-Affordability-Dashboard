"""
etl_fred_mortgage.py
ETL script: FRED - 30-Year Fixed Mortgage Rate (MORTGAGE30US)
Extracts weekly mortgage rate data, loads into:
  staging.mortgage_rates  →  prod.fact_mortgage_rates

Source: FRED API (Federal Reserve Bank of St. Louis)
Series: MORTGAGE30US - 30-Year Fixed Rate Mortgage Average
        Published weekly by Freddie Mac via FRED

FRED API key: Free at https://fred.stlouisfed.org/docs/api/api_key.html
(Optional — FRED allows limited calls without a key)

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

LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_fred_mortgage.log")
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
# FRED API key (optional but recommended)
# Free at: https://fred.stlouisfed.org/docs/api/api_key.html
# Without a key FRED allows 1000 requests/day which is fine here
# ----------------------------------------------------------------
FRED_API_KEY = "YOUR_FRED_API_KEY_HERE"

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series ID for 30-year fixed mortgage rate
SERIES_ID = "MORTGAGE30US"


# ----------------------------------------------------------------
# Helper: safe float
# ----------------------------------------------------------------
def safe_float(val):
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------
# Step 1: Download from FRED API
# ----------------------------------------------------------------
def download_fred():
    logging.info(f"Downloading FRED series: {SERIES_ID}...")

    params = {
        "series_id":         SERIES_ID,
        "observation_start": "2015-01-01",
        "observation_end":   "2026-12-31",
        "file_type":         "json",
        "frequency":         "m",       # Monthly average
        "aggregation_method": "avg",    # Average weekly rates into monthly
    }

    if FRED_API_KEY != "YOUR_FRED_API_KEY_HERE":
        params["api_key"] = FRED_API_KEY
    else:
        # FRED requires api_key param — use a no-key workaround via direct CSV
        logging.warning("No FRED API key set. Attempting CSV download fallback...")
        return download_fred_csv()

    try:
        response = requests.get(FRED_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        observations = data.get("observations", [])
        logging.info(f"Fetched {len(observations)} observations from FRED API")

        records = []
        for obs in observations:
            date_str = obs.get("date", "")
            value    = obs.get("value", ".")

            if value == "." or not date_str:
                continue

            records.append({
                "report_date":    date_str,
                "rate_30yr_fixed": safe_float(value),
            })

        df = pd.DataFrame(records)
        df['report_date'] = pd.to_datetime(df['report_date'])
        df = df.dropna(subset=['rate_30yr_fixed'])

        logging.info(f"Parsed {len(df)} monthly mortgage rate observations")
        return df

    except Exception as e:
        logging.error(f"FRED API download failed: {e}")
        logging.info("Trying CSV fallback...")
        return download_fred_csv()


def download_fred_csv():
    """
    Fallback: download MORTGAGE30US directly as CSV from FRED.
    No API key needed for this endpoint.
    """
    csv_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"

    try:
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()

        from io import StringIO
        df_raw = pd.read_csv(StringIO(response.text))

        # CSV columns: DATE, MORTGAGE30US
        df_raw.columns = ['report_date', 'rate_30yr_fixed']
        df_raw['report_date']    = pd.to_datetime(df_raw['report_date'], errors='coerce')
        df_raw['rate_30yr_fixed'] = pd.to_numeric(df_raw['rate_30yr_fixed'], errors='coerce')
        df_raw = df_raw.dropna()

        # Filter to 2015+
        df_raw = df_raw[df_raw['report_date'] >= '2015-01-01']

        # Aggregate weekly → monthly (use month-end date, average rate)
        df_raw['report_date'] = df_raw['report_date'].dt.to_period('M').dt.to_timestamp()
        df_monthly = df_raw.groupby('report_date')['rate_30yr_fixed'].mean().reset_index()
        df_monthly['rate_30yr_fixed'] = df_monthly['rate_30yr_fixed'].apply(
            lambda x: round(x, 4) if x else None
        )

        logging.info(f"CSV fallback: fetched {len(df_monthly)} monthly records")
        return df_monthly

    except Exception as e:
        logging.error(f"CSV fallback also failed: {e}")
        raise


# ----------------------------------------------------------------
# Step 2: Load into staging.mortgage_rates
# ----------------------------------------------------------------
def load_staging(df):
    logging.info("Loading into staging.mortgage_rates...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE staging.mortgage_rates;")
    conn.commit()
    logging.info("Truncated staging.mortgage_rates")

    insert_sql = """
        INSERT INTO staging.mortgage_rates
            (report_date, rate_30yr_fixed, data_source)
        VALUES (?, ?, ?)
    """

    rows_inserted = 0
    errors = 0

    for _, row in df.iterrows():
        try:
            cursor.execute(insert_sql, (
                row['report_date'].date(),
                safe_float(row['rate_30yr_fixed']),
                'FRED MORTGAGE30US'
            ))
            rows_inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logging.warning(f"Insert failed: {e} | {row['report_date']}")

    conn.commit()
    conn.close()
    logging.info(f"Staging: {rows_inserted} rows, {errors} errors")
    return rows_inserted


# ----------------------------------------------------------------
# Step 3: Load into prod.fact_mortgage_rates
# ----------------------------------------------------------------
def load_fact():
    logging.info("Loading into prod.fact_mortgage_rates...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE prod.fact_mortgage_rates;")
    conn.commit()

    cursor.execute("""
        INSERT INTO prod.fact_mortgage_rates
            (date_id, rate_30yr_fixed, data_source)
        SELECT
            CAST(FORMAT(s.report_date, 'yyyyMMdd') AS INT),
            s.rate_30yr_fixed,
            s.data_source
        FROM staging.mortgage_rates s
        WHERE s.rate_30yr_fixed IS NOT NULL;
    """)

    rows = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"prod.fact_mortgage_rates: {rows} rows")
    return rows


# ----------------------------------------------------------------
# Step 4: Validation
# ----------------------------------------------------------------
def validate():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            MIN(d.full_date)        AS earliest,
            MAX(d.full_date)        AS latest,
            COUNT(*)                AS row_count,
            AVG(m.rate_30yr_fixed)  AS avg_rate,
            MIN(m.rate_30yr_fixed)  AS min_rate,
            MAX(m.rate_30yr_fixed)  AS max_rate
        FROM prod.fact_mortgage_rates m
        JOIN prod.dim_date d ON m.date_id = d.date_id;
    """)

    row = cursor.fetchone()
    print("\n--- Validation: fact_mortgage_rates ---")
    print(f"  Date range : {row.earliest} → {row.latest}")
    print(f"  Row count  : {row.row_count}")
    print(f"  Avg rate   : {row.avg_rate:.4f}%")
    print(f"  Min rate   : {row.min_rate:.4f}% (COVID-era lows)")
    print(f"  Max rate   : {row.max_rate:.4f}% (2023 peak)")

    # Show last 12 months
    cursor.execute("""
        SELECT TOP 12
            d.full_date,
            m.rate_30yr_fixed
        FROM prod.fact_mortgage_rates m
        JOIN prod.dim_date d ON m.date_id = d.date_id
        ORDER BY d.full_date DESC;
    """)

    rows = cursor.fetchall()
    print("\n  Last 12 months:")
    for r in rows:
        print(f"    {r.full_date}  {r.rate_30yr_fixed:.2f}%")

    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("ETL START: FRED Mortgage Rates")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)

    try:
        df       = download_fred()
        load_staging(df)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: FRED Mortgage Rates")

    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
