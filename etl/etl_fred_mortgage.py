"""
etl_fred_mortgage.py
ETL script: FRED - 30-Year Fixed Mortgage Rate (MORTGAGE30US)
Extracts weekly mortgage rate data, loads into:
  staging.mortgage_rates  ->  prod.fact_mortgage_rates

Source: FRED API (Federal Reserve Bank of St. Louis)
Series: MORTGAGE30US - 30-Year Fixed Rate Mortgage Average

FRED API key (optional): https://fred.stlouisfed.org/docs/api/api_key.html
Set FRED_API_KEY in your .env file. A CSV fallback works without a key.
"""

import os
import sys
import logging
import math
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ----------------------------------------------------------------
# Project root and paths
# ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))
from db_utils import get_connection

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "etl_fred_mortgage.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------
# FRED API key — loaded from .env (optional)
# ----------------------------------------------------------------
FRED_API_KEY  = os.getenv("FRED_API_KEY", "")
FRED_API_URL  = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID     = "MORTGAGE30US"


def safe_float(val):
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (ValueError, TypeError):
        return None


def download_fred_api():
    params = {
        "series_id":          SERIES_ID,
        "observation_start":  "2015-01-01",
        "observation_end":    "2026-12-31",
        "file_type":          "json",
        "frequency":          "m",
        "aggregation_method": "avg",
        "api_key":            FRED_API_KEY,
    }
    try:
        response = requests.get(FRED_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        observations = data.get("observations", [])
        logging.info(f"Fetched {len(observations)} observations from FRED API")

        records = []
        for obs in observations:
            value = obs.get("value", ".")
            if value == ".":
                continue
            records.append({
                "report_date":     obs.get("date"),
                "rate_30yr_fixed": safe_float(value),
            })

        df = pd.DataFrame(records)
        df['report_date'] = pd.to_datetime(df['report_date'])
        return df.dropna(subset=['rate_30yr_fixed'])

    except Exception as e:
        logging.warning(f"FRED API failed: {e}")
        return None


def download_fred_csv():
    """CSV fallback — no API key required."""
    csv_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"
    try:
        response = requests.get(csv_url, timeout=30)
        response.raise_for_status()
        from io import StringIO
        df_raw = pd.read_csv(StringIO(response.text))
        df_raw.columns = ['report_date', 'rate_30yr_fixed']
        df_raw['report_date']     = pd.to_datetime(df_raw['report_date'], errors='coerce')
        df_raw['rate_30yr_fixed'] = pd.to_numeric(df_raw['rate_30yr_fixed'], errors='coerce')
        df_raw = df_raw.dropna()
        df_raw = df_raw[df_raw['report_date'] >= '2015-01-01']

        # Aggregate weekly -> monthly
        df_raw['report_date'] = df_raw['report_date'].dt.to_period('M').dt.to_timestamp()
        df_monthly = df_raw.groupby('report_date')['rate_30yr_fixed'].mean().reset_index()
        df_monthly['rate_30yr_fixed'] = df_monthly['rate_30yr_fixed'].apply(
            lambda x: round(x, 4) if x else None
        )
        logging.info(f"CSV fallback: {len(df_monthly)} monthly records")
        return df_monthly

    except Exception as e:
        logging.error(f"CSV fallback failed: {e}")
        raise


def download_fred():
    if FRED_API_KEY:
        df = download_fred_api()
        if df is not None and not df.empty:
            return df
        logging.warning("FRED API failed. Trying CSV fallback...")
    else:
        logging.info("No FRED API key — using CSV fallback (no key required).")

    return download_fred_csv()


def load_staging(df):
    logging.info("Loading into staging.mortgage_rates...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.mortgage_rates;")
    conn.commit()

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
                logging.warning(f"Insert failed: {e}")

    conn.commit()
    conn.close()
    logging.info(f"Staging: {rows_inserted} rows, {errors} errors")
    return rows_inserted


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


def validate():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MIN(d.full_date) AS earliest, MAX(d.full_date) AS latest,
               COUNT(*) AS row_count,
               AVG(m.rate_30yr_fixed) AS avg_rate,
               MIN(m.rate_30yr_fixed) AS min_rate,
               MAX(m.rate_30yr_fixed) AS max_rate
        FROM prod.fact_mortgage_rates m
        JOIN prod.dim_date d ON m.date_id = d.date_id;
    """)
    row = cursor.fetchone()
    print("\n--- Validation: fact_mortgage_rates ---")
    print(f"  Date range : {row.earliest} -> {row.latest}")
    print(f"  Row count  : {row.row_count}")
    print(f"  Avg rate   : {row.avg_rate:.4f}%")
    print(f"  Min rate   : {row.min_rate:.4f}%")
    print(f"  Max rate   : {row.max_rate:.4f}%")
    conn.close()


def main():
    logging.info("=" * 60)
    logging.info("ETL START: FRED Mortgage Rates")
    logging.info(f"Run time: {datetime.now()}")
    logging.info("=" * 60)
    try:
        df = download_fred()
        load_staging(df)
        load_fact()
        validate()
        logging.info("ETL COMPLETE: FRED Mortgage Rates")
    except Exception as e:
        logging.error(f"ETL FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
