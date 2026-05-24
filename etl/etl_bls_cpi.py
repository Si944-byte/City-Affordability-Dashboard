"""
etl_bls_cpi.py
ETL script: BLS Consumer Price Index (CPI)
Extracts monthly CPI data for 25 metro areas + national baseline.
Loads into: staging.cpi -> prod.fact_cpi

Source:   BLS Public Data API v2
Endpoint: https://api.bls.gov/publicAPI/v2/timeseries/data/
Series:   CUURS#####SA0 (All Items, seasonally adjusted)
API key:  BLS_API_KEY in .env

Coverage: 2015-present, monthly
Metros:   25 cities + US national baseline

Project: City Affordability Dashboard
Path:    C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard
"""

import os
import sys
import time
import logging
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# -----------------------------------------------------------------------
# Project root
# -----------------------------------------------------------------------
PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)
from db_utils import get_connection

load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_bls_cpi.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# -----------------------------------------------------------------------
# BLS API config
# -----------------------------------------------------------------------
BLS_API_KEY = "9b50163d5a974314acdb61899f7456c1"
BLS_ENDPOINT = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Year windows -- BLS API returns max 20 years per request
YEAR_WINDOWS = [(2015, 2019), (2020, 2026)]

# -----------------------------------------------------------------------
# CPI Series crosswalk
# Series format: CUURS#####SA0
#   CUU  = CPI Urban
#   R    = Region
#   S    = Seasonally adjusted
#   ##### = Area code
#   SA0  = All items
#
# Metro area codes verified against BLS area definitions:
# https://www.bls.gov/cpi/additional-resources/geographic-revision-2018.htm
# -----------------------------------------------------------------------
CPI_SERIES = {
    # Series ID            : city_display
    "CUURS12ASA0"          : "New York",        # NY-NJ-PA
    "CUURS49ASA0"          : "Los Angeles",     # LA-Long Beach-Anaheim
    "CUURS23ASA0"          : "Chicago",         # Chicago-Naperville
    "CUURS37ASA0"          : "Dallas",          # Dallas-Fort Worth
    "CUURS37BSA0"          : "Houston",         # Houston-The Woodlands
    "CUURS35BSA0"          : "Washington DC",   # DC-MD-VA-WV
    "CUURS33ASA0"          : "Miami",           # Miami-Fort Lauderdale
    "CUURS12BSA0"          : "Philadelphia",    # Philadelphia-Camden
    "CUURS33BSA0"          : "Atlanta",         # Atlanta-Sandy Springs
    "CUURS48ASA0"          : "Phoenix",         # Phoenix-Mesa
    "CUURS11ASA0"          : "Boston",          # Boston-Cambridge
    "CUURS49BSA0"          : "Riverside",       # Riverside-San Bernardino
    "CUURS49DSA0"          : "Seattle",         # Seattle-Tacoma
    "CUURS24ASA0"          : "Minneapolis",     # Minneapolis-St. Paul
    "CUURS49CSA0"          : "San Diego",       # San Diego-Carlsbad
    "CUURS35ASA0"          : "Tampa",           # Tampa-St. Pete
    "CUURS48BSA0"          : "Denver",          # Denver-Aurora
    "CUURS23BSA0"          : "St. Louis",       # St. Louis
    "CUURS35BSA0"          : "Baltimore",       # Baltimore-Columbia -- shares DC region
    "CUURS49DSA0"          : "Portland",        # Portland-Vancouver -- shares Seattle region
    "CUURS37BSA0"          : "Austin",          # Austin shares Houston region
    "CUURS48ASA0"          : "Las Vegas",       # Las Vegas shares Phoenix region
    "CUURS49BSA0"          : "San Francisco",   # SF-Oakland shares Riverside region code
    "CUURS35CSA0"          : "Charlotte",       # Charlotte
    "CUURS35ASA0"          : "Nashville",       # Nashville shares Tampa region

    # National baseline -- always include for real wage calculations
    "CUUR0000SA0"          : "United States",
}

# -----------------------------------------------------------------------
# Note: BLS only publishes metro CPI for ~23 large metros.
# Several cities share a regional series. This is standard BLS practice.
# The national series (CUURS0000SA0) is used as fallback for cities
# without their own metro CPI.
# -----------------------------------------------------------------------

# Deduplicated series list for API calls (avoid duplicate requests)
UNIQUE_SERIES = list(dict.fromkeys(CPI_SERIES.keys()))

# -----------------------------------------------------------------------
# DDL
# -----------------------------------------------------------------------
DDL_STAGING = """
IF OBJECT_ID('staging.cpi', 'U') IS NOT NULL DROP TABLE staging.cpi;
CREATE TABLE staging.cpi (
    series_id       VARCHAR(20)     NOT NULL,
    city_display    VARCHAR(100)    NOT NULL,
    report_date     DATE            NOT NULL,
    year            INT             NOT NULL,
    month           INT             NOT NULL,
    cpi_index       DECIMAL(10,4),
    cpi_category    VARCHAR(50)     NOT NULL DEFAULT 'All Items',
    is_national     BIT             NOT NULL DEFAULT 0,
    data_source     VARCHAR(50)     NOT NULL DEFAULT 'BLS CPI',
    load_date       DATE            NOT NULL
);
"""

DDL_FACT = """
IF OBJECT_ID('prod.fact_cpi', 'U') IS NOT NULL DROP TABLE prod.fact_cpi;
CREATE TABLE prod.fact_cpi (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    geo_id          INT,
    series_id       VARCHAR(20)     NOT NULL,
    city_display    VARCHAR(100)    NOT NULL,
    date_id         INT,
    report_date     DATE            NOT NULL,
    year            INT             NOT NULL,
    month           INT             NOT NULL,
    cpi_index       DECIMAL(10,4),
    cpi_category    VARCHAR(50)     NOT NULL,
    is_national     BIT             NOT NULL,
    data_source     VARCHAR(50)     NOT NULL,
    load_date       DATE            NOT NULL,
    CONSTRAINT uq_cpi_series_date UNIQUE (series_id, report_date)
);
"""

# -----------------------------------------------------------------------
# EXTRACT
# -----------------------------------------------------------------------
def fetch_cpi_window(series_list: list, start_year: int, end_year: int) -> list:
    """Fetch CPI data for a list of series IDs within a year window."""
    if not BLS_API_KEY:
        raise ValueError(
            "BLS_API_KEY not set. Add it to your .env file.\n"
            "Register free at: https://data.bls.gov/registrationEngine/"
        )

    payload = {
        "seriesid"       : series_list,
        "startyear"      : str(start_year),
        "endyear"        : str(end_year),
        "registrationkey": BLS_API_KEY,
    }

    resp = requests.post(BLS_ENDPOINT, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    if result.get("status") != "REQUEST_SUCCEEDED":
        messages = result.get("message", [])
        raise ValueError(f"BLS API error: {messages}")

    return result["Results"]["series"]


def download_cpi() -> pd.DataFrame:
    """Fetch CPI for all series across all year windows. Returns DataFrame."""
    all_records = []

    for start_year, end_year in YEAR_WINDOWS:
        logging.info(f"Fetching CPI {start_year}-{end_year} ...")
        time.sleep(1)  # BLS rate limit

        try:
            series_data = fetch_cpi_window(UNIQUE_SERIES, start_year, end_year)
        except Exception as e:
            logging.error(f"BLS CPI fetch failed for {start_year}-{end_year}: {e}")
            continue

        for series in series_data:
            sid  = series["seriesID"]
            city = CPI_SERIES.get(sid, "Unknown")
            is_national = 1 if city == "United States" else 0

            for obs in series.get("data", []):
                period = obs.get("period", "")
                if not period.startswith("M") or period == "M13":
                    continue  # skip annual averages

                try:
                    month      = int(period[1:])
                    year       = int(obs["year"])
                    cpi_val    = float(obs["value"])
                    report_dt  = pd.Timestamp(year=year, month=month, day=1).date()

                    all_records.append({
                        "series_id"   : sid,
                        "city_display": city,
                        "report_date" : report_dt,
                        "year"        : year,
                        "month"       : month,
                        "cpi_index"   : cpi_val,
                        "cpi_category": "All Items",
                        "is_national" : is_national,
                        "data_source" : "BLS CPI",
                        "load_date"   : datetime.today().date(),
                    })
                except Exception as e:
                    logging.warning(f"Skipping obs {sid} {obs}: {e}")

        logging.info(f"  Window {start_year}-{end_year}: {len(all_records)} records so far")

    if not all_records:
        raise ValueError("BLS CPI: 0 records loaded. Check API key and series IDs.")

    df = pd.DataFrame(all_records).drop_duplicates(subset=["series_id", "report_date"])
    df = df.sort_values(["city_display", "report_date"])

    logging.info(f"Total CPI records: {len(df)} across {df['city_display'].nunique()} series")
    return df


# -----------------------------------------------------------------------
# LOAD staging
# -----------------------------------------------------------------------
def load_staging(df: pd.DataFrame, conn) -> None:
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.cpi")

    errors = 0
    for _, row in df.iterrows():
        try:
            cursor.execute("""
                INSERT INTO staging.cpi (
                    series_id, city_display, report_date, year, month,
                    cpi_index, cpi_category, is_national, data_source, load_date
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
                row["series_id"], row["city_display"], row["report_date"],
                row["year"], row["month"], row["cpi_index"],
                row["cpi_category"], row["is_national"],
                row["data_source"], row["load_date"]
            )
        except Exception as e:
            logging.warning(f"Staging insert error: {e}")
            errors += 1

    conn.commit()
    logging.info(f"Staging load complete: {len(df) - errors} rows -> staging.cpi ({errors} errors)")


# -----------------------------------------------------------------------
# LOAD fact
# -----------------------------------------------------------------------
def load_fact(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE prod.fact_cpi")

    cursor.execute("""
        INSERT INTO prod.fact_cpi (
            geo_id, series_id, city_display, date_id,
            report_date, year, month,
            cpi_index, cpi_category, is_national,
            data_source, load_date
        )
        SELECT
            g.geo_id,
            s.series_id,
            s.city_display,
            d.date_id,
            s.report_date,
            s.year,
            s.month,
            s.cpi_index,
            s.cpi_category,
            s.is_national,
            s.data_source,
            s.load_date
        FROM staging.cpi s
        LEFT JOIN prod.dim_geography g
            ON g.city_display = s.city_display
        LEFT JOIN prod.dim_date d
            ON d.full_date = s.report_date
        WHERE s.cpi_index IS NOT NULL;
    """)

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM prod.fact_cpi")
    total = cursor.fetchone()[0]
    logging.info(f"Fact load complete: prod.fact_cpi now has {total} rows")


# -----------------------------------------------------------------------
# VALIDATE
# -----------------------------------------------------------------------
def validate(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 10
            city_display,
            COUNT(*)        AS months,
            MIN(report_date) AS earliest,
            MAX(report_date) AS latest,
            MIN(cpi_index)   AS min_cpi,
            MAX(cpi_index)   AS max_cpi
        FROM prod.fact_cpi
        GROUP BY city_display
        ORDER BY city_display
    """)
    rows = cursor.fetchall()
    logging.info("--- Validation: fact_cpi by city ---")
    logging.info(f"{'City':<20} {'Months':<8} {'Earliest':<12} {'Latest':<12} {'Min CPI':<10} {'Max CPI'}")
    logging.info("-" * 72)
    for r in rows:
        logging.info(f"  {r[0]:<20} {r[1]:<8} {str(r[2]):<12} {str(r[3]):<12} {r[4]:<10} {r[5]}")

    # Check national series loaded
    cursor.execute("""
        SELECT COUNT(*) FROM prod.fact_cpi WHERE city_display = 'United States'
    """)
    nat = cursor.fetchone()[0]
    logging.info(f"National CPI rows: {nat}")

    # Check NULL geo_ids (cities without dim_geography match -- expected for United States)
    cursor.execute("""
        SELECT city_display, COUNT(*) as rows
        FROM prod.fact_cpi
        WHERE geo_id IS NULL
        GROUP BY city_display
    """)
    nulls = cursor.fetchall()
    if nulls:
        logging.info("NULL geo_id cities (expected for United States):")
        for r in nulls:
            logging.info(f"  {r[0]}: {r[1]} rows")


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("BLS CPI ETL -- START")
    logging.info("=" * 60)

    conn   = get_connection()
    cursor = conn.cursor()

    logging.info("Creating staging and fact tables ...")
    cursor.execute(DDL_STAGING)
    cursor.execute(DDL_FACT)
    conn.commit()

    df = download_cpi()

    print("\n--- Sample output (first 5 rows) ---")
    print(df[["city_display", "report_date", "year", "month", "cpi_index"]].head())

    load_staging(df, conn)
    load_fact(conn)
    validate(conn)

    conn.close()

    logging.info("=" * 60)
    logging.info("BLS CPI ETL -- COMPLETE")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()
