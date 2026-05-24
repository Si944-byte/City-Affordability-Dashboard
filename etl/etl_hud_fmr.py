"""
etl_hud_fmr.py
ETL script: HUD Fair Market Rents (FMR)
Extracts annual fair market rent data for the top 25 metros, loads into:
  staging.hud_fmr  →  prod.fact_hud_fmr

Source:   HUD Fair Market Rents API
Endpoint: https://www.huduser.gov/hudapi/public/fmr/data/{entityid}
Auth:     Bearer token — free at https://www.huduser.gov/portal/dataset/fmr-api.html

Bedroom types: Efficiency (0BR), 1BR, 2BR, 3BR, 4BR

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

# -----------------------------------------------------------------------
# Project root on path so db_utils is importable
# -----------------------------------------------------------------------
PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)
from db_utils import get_connection

# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
LOG_FILE = os.path.join(PROJECT_DIR, "logs", "etl_hud_fmr.log")
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
# !! ENTER YOUR HUD API KEY HERE !!
# Free registration: https://www.huduser.gov/portal/dataset/fmr-api.html
# -----------------------------------------------------------------------
HUD_API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI2IiwianRpIjoiYzIyMTlmODkyMTljNzlhMTg0MjQ2MDcwZmM4OTA5ZGMyYzJlOTQwNTRlNzY0YmVhODBhZWJhNDNhNzIxNDBkNDUzYTRiNmJkYWVkMWQ1OTciLCJpYXQiOjE3NzkzOTQ5MjcuOTg0MTE2LCJuYmYiOjE3NzkzOTQ5MjcuOTg0MTE5LCJleHAiOjIwOTUwMTQxMjcuOTc4OTI2LCJzdWIiOiIxMjkyNDIiLCJzY29wZXMiOltdfQ.FzQeD86iHXFmnykGxUMmZ1YnQQZE5GtX6-40l4G0vZ0Y6IJq08dqFNNclJoYIuRT29yzjYqLBrpz-bfjATysuQ"

# -----------------------------------------------------------------------
# HUD API config
# Endpoint: /fmr/data/{entityid}  — returns FMR by metro entity ID
# Year param selects fiscal year; falls back through recent years if
# the requested year is not yet published.
# -----------------------------------------------------------------------
BASE_URL        = "https://www.huduser.gov/hudapi/public/fmr/data/{entityid}"
YEARS_TO_TRY    = [2026, 2025, 2024, 2023]   # newest first; stops at first success

# -----------------------------------------------------------------------
# Top-25 metro crosswalk
# Keys   : HUD entity ID  (used in the API call)
# Values : canonical city name matching Dim_Geography in the database
#
# Entity IDs confirmed against HUD API docs and the /fmr/listMetroAreas
# endpoint.  Format: METRO{cbsa_code}M{cbsa_code}
# -----------------------------------------------------------------------
METRO_CROSSWALK = {
    # Entity ID                  : Canonical city name
    # Codes verified against HUD listMetroAreas endpoint May 2026
    # Large metros use HUD subdivision codes (MM####), not raw CBSA codes
    "METRO35620MM5600"           : "New York",          # NY HUD Metro FMR Area
    "METRO31080MM4480"           : "Los Angeles",       # LA-Long Beach-Glendale HUD Metro FMR Area
    "METRO16980M16980"           : "Chicago",
    "METRO19100M19100"           : "Dallas",
    "METRO26420M26420"           : "Houston",
    "METRO33100MM5000"           : "Miami",             # Miami-Miami Beach-Kendall HUD Metro FMR Area
    "METRO47900M47900"           : "Washington DC",
    "METRO37980M37980"           : "Philadelphia",
    "METRO12060M12060"           : "Atlanta",
    "METRO38060M38060"           : "Phoenix",
    "METRO14460MM1120"           : "Boston",            # Boston-Cambridge-Quincy HUD Metro FMR Area
    "METRO40140M40140"           : "Riverside",
    "METRO42660MM7600"           : "Seattle",           # Seattle-Bellevue HUD Metro FMR Area
    "METRO33460M33460"           : "Minneapolis",
    "METRO41740M41740"           : "San Diego",
    "METRO45300M45300"           : "Tampa",
    "METRO19740M19740"           : "Denver",
    "METRO41180M41180"           : "St. Louis",
    "METRO12580M12580"           : "Baltimore",
    "METRO38900M38900"           : "Portland",          # Portland-Vancouver-Hillsboro OR-WA
    "METRO12420M12420"           : "Austin",            # Austin-Round Rock TX
    "METRO29820M29820"           : "Las Vegas",
    "METRO41860MM7360"           : "San Francisco",     # San Francisco HUD Metro FMR Area
    "METRO16740M16740"           : "Charlotte",
    "METRO34980M34980"           : "Nashville",
}

# -----------------------------------------------------------------------
# DDL — run once to create tables if they don't already exist
# -----------------------------------------------------------------------
DDL_STAGING = """
IF OBJECT_ID('staging.hud_fmr', 'U') IS NOT NULL DROP TABLE staging.hud_fmr;
CREATE TABLE staging.hud_fmr (
    entity_id       VARCHAR(30)     NOT NULL,
    city            VARCHAR(100)    NOT NULL,
    metro_name      VARCHAR(200),
    fmr_year        INT             NOT NULL,
    fmr_0br         DECIMAL(10,2),
    fmr_1br         DECIMAL(10,2),
    fmr_2br         DECIMAL(10,2),
    fmr_3br         DECIMAL(10,2),
    fmr_4br         DECIMAL(10,2),
    fmr_percentile  INT,
    smallarea_flag  TINYINT,
    load_date       DATE            NOT NULL
);
"""

DDL_FACT = """
IF OBJECT_ID('prod.fact_hud_fmr', 'U') IS NOT NULL DROP TABLE prod.fact_hud_fmr;
CREATE TABLE prod.fact_hud_fmr (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    entity_id       VARCHAR(30)     NOT NULL,
    city            VARCHAR(100)    NOT NULL,
    metro_name      VARCHAR(200),
    fmr_year        INT             NOT NULL,
    fmr_0br         DECIMAL(10,2),
    fmr_1br         DECIMAL(10,2),
    fmr_2br         DECIMAL(10,2),
    fmr_3br         DECIMAL(10,2),
    fmr_4br         DECIMAL(10,2),
    fmr_percentile  INT,
    smallarea_flag  TINYINT,
    load_date       DATE            NOT NULL,
    CONSTRAINT uq_fmr_city_year UNIQUE (entity_id, fmr_year)
);
"""

# -----------------------------------------------------------------------
# EXTRACT
# -----------------------------------------------------------------------
def fetch_metro(session: requests.Session, entity_id: str, city: str) -> dict | None:
    """
    Fetch FMR data for a single metro entity ID.
    Tries each year in YEARS_TO_TRY and returns the first successful result.
    Returns None if all years fail.
    """
    for year in YEARS_TO_TRY:
        url    = BASE_URL.format(entityid=entity_id)
        params = {"year": year}
        try:
            # Respect HUD rate limits — pause between every request
            time.sleep(3.0)

            resp = session.get(url, params=params, timeout=20)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logging.warning(
                    f"  {city} ({entity_id}) year={year}: 429 rate limited — "
                    f"waiting {retry_after}s before retry"
                )
                time.sleep(retry_after)
                # One more pause after the retry window before hitting again
                time.sleep(3.0)
                resp = session.get(url, params=params, timeout=20)

            if resp.status_code == 404:
                logging.warning(f"  {city} ({entity_id}) year={year}: 404 — trying next year")
                continue

            resp.raise_for_status()
            payload = resp.json()

            # HUD returns data nested under the "data" key.
            # For some metros the value is a JSON-encoded string -- parse it.
            data_block = payload.get("data", {})
            if isinstance(data_block, str):
                import json as _json
                try:
                    data_block = _json.loads(data_block)
                except Exception:
                    logging.error(
                        f"  {city} ({entity_id}) year={year}: "
                        "data field is a non-parseable string -- skipping"
                    )
                    continue

            # HUD returns FMR values in one of three formats:
            # Format A: basicdata is a LIST of dicts; find the row where zip_code == "MSA level"
            # Format B: basicdata is a DICT with bedroom keys directly (most MSA-level metros)
            # Format C: bedroom keys sit directly on data_block (oldest format)
            basicdata = data_block.get("basicdata") if isinstance(data_block, dict) else None

            if isinstance(basicdata, dict):
                # Format B -- bedroom values are directly on the basicdata dict
                msa_row = basicdata

            elif isinstance(basicdata, list):
                # Format A -- find the MSA-level row in the list
                msa_row = next(
                    (r for r in basicdata if str(r.get("zip_code", "")).strip().lower() == "msa level"),
                    None
                )
                # If no MSA-level row, take the first row
                if not msa_row and basicdata:
                    msa_row = basicdata[0]

            else:
                # Format C -- values sit directly on data_block
                msa_row = data_block if isinstance(data_block, dict) else {}

            if not any(msa_row.values()):
                logging.warning(f"  {city} ({entity_id}) year={year}: no MSA-level FMR values found")
                continue

            logging.info(f"  {city} ({entity_id}) year={year}: OK — "
                         f"2BR=${msa_row.get('Two-Bedroom')}")

            return {
                "entity_id"     : entity_id,
                "city"          : city,
                "metro_name"    : data_block.get("metro_name", ""),
                "fmr_year"      : int(data_block.get("year", year)),
                "fmr_0br"       : msa_row.get("Efficiency"),
                "fmr_1br"       : msa_row.get("One-Bedroom"),
                "fmr_2br"       : msa_row.get("Two-Bedroom"),
                "fmr_3br"       : msa_row.get("Three-Bedroom"),
                "fmr_4br"       : msa_row.get("Four-Bedroom"),
                "fmr_percentile": data_block.get("FMR Percentile"),
                "smallarea_flag": int(str(data_block.get("smallarea_status", "0")) == "1"),
                "load_date"     : datetime.today().date(),
            }

        except requests.exceptions.RequestException as e:
            logging.error(f"  {city} ({entity_id}) year={year}: request error — {e}")
            continue
        except Exception as e:
            logging.error(f"  {city} ({entity_id}) year={year}: unexpected error — {e}")
            continue

    logging.error(f"  {city} ({entity_id}): ALL years failed — skipping")
    return None


def download_hud() -> pd.DataFrame:
    """Fetch FMR data for all 25 metros. Returns a DataFrame."""
    if HUD_API_KEY == "YOUR_HUD_API_KEY_HERE":
        raise ValueError(
            "HUD API key not set. Open etl_hud_fmr.py and replace "
            "'YOUR_HUD_API_KEY_HERE' with your key from "
            "https://www.huduser.gov/portal/dataset/fmr-api.html"
        )

    headers = {"Authorization": f"Bearer {HUD_API_KEY}"}
    session = requests.Session()
    session.headers.update(headers)

    records = []
    total   = len(METRO_CROSSWALK)

    logging.info(f"Fetching HUD FMR data for {total} metros ...")

    for i, (entity_id, city) in enumerate(METRO_CROSSWALK.items(), start=1):
        logging.info(f"[{i}/{total}] {city}")
        result = fetch_metro(session, entity_id, city)
        if result:
            records.append(result)

    if not records:
        raise ValueError(
            "HUD FMR ETL: 0 records loaded. "
            "Check your API key, internet connection, and logs."
        )

    df = pd.DataFrame(records)
    logging.info(f"Total records fetched: {len(df)} of {total} metros")
    return df


# -----------------------------------------------------------------------
# LOAD — staging
# -----------------------------------------------------------------------
def load_staging(df: pd.DataFrame, conn) -> None:
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE staging.hud_fmr")

    for _, row in df.iterrows():
        cursor.execute(
            """
            INSERT INTO staging.hud_fmr (
                entity_id, city, metro_name, fmr_year,
                fmr_0br, fmr_1br, fmr_2br, fmr_3br, fmr_4br,
                fmr_percentile, smallarea_flag, load_date
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            row["entity_id"], row["city"], row["metro_name"], row["fmr_year"],
            row["fmr_0br"], row["fmr_1br"], row["fmr_2br"],
            row["fmr_3br"], row["fmr_4br"],
            row["fmr_percentile"], row["smallarea_flag"], row["load_date"],
        )

    conn.commit()
    logging.info(f"Staging load complete: {len(df)} rows -> staging.hud_fmr")


# -----------------------------------------------------------------------
# LOAD — production fact table (upsert by entity_id + fmr_year)
# -----------------------------------------------------------------------
def load_fact(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        MERGE prod.fact_hud_fmr AS target
        USING staging.hud_fmr   AS source
        ON  target.entity_id = source.entity_id
        AND target.fmr_year  = source.fmr_year
        WHEN MATCHED THEN
            UPDATE SET
                city            = source.city,
                metro_name      = source.metro_name,
                fmr_0br         = source.fmr_0br,
                fmr_1br         = source.fmr_1br,
                fmr_2br         = source.fmr_2br,
                fmr_3br         = source.fmr_3br,
                fmr_4br         = source.fmr_4br,
                fmr_percentile  = source.fmr_percentile,
                smallarea_flag  = source.smallarea_flag,
                load_date       = source.load_date
        WHEN NOT MATCHED THEN
            INSERT (
                entity_id, city, metro_name, fmr_year,
                fmr_0br, fmr_1br, fmr_2br, fmr_3br, fmr_4br,
                fmr_percentile, smallarea_flag, load_date
            )
            VALUES (
                source.entity_id, source.city, source.metro_name, source.fmr_year,
                source.fmr_0br, source.fmr_1br, source.fmr_2br, source.fmr_3br, source.fmr_4br,
                source.fmr_percentile, source.smallarea_flag, source.load_date
            );
        """
    )
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM prod.fact_hud_fmr")
    total_rows = cursor.fetchone()[0]
    logging.info(f"Fact load complete: prod.fact_hud_fmr now has {total_rows} total rows")


# -----------------------------------------------------------------------
# VALIDATE
# -----------------------------------------------------------------------
def validate(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT TOP 25
            city,
            fmr_year,
            fmr_1br,
            fmr_2br,
            fmr_3br
        FROM prod.fact_hud_fmr
        ORDER BY fmr_2br DESC
        """
    )
    rows = cursor.fetchall()
    logging.info("--- Validation: 2BR FMR by city (highest to lowest) ---")
    for r in rows:
        logging.info(f"  {r[0]:<20} year={r[1]}  1BR=${r[2]}  2BR=${r[3]}  3BR=${r[4]}")


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
def main():
    logging.info("=" * 60)
    logging.info("HUD FMR ETL — START")
    logging.info("=" * 60)

    conn = get_connection()
    cursor = conn.cursor()

    # Create tables if they don't exist
    logging.info("Ensuring staging and fact tables exist ...")
    cursor.execute(DDL_STAGING)
    cursor.execute(DDL_FACT)
    conn.commit()

    # Extract
    df = download_hud()

    # Preview
    print("\n--- Sample output (first 5 rows) ---")
    print(df[["city", "fmr_year", "fmr_1br", "fmr_2br", "fmr_3br"]].head())

    # Load
    load_staging(df, conn)
    load_fact(conn)

    # Validate
    validate(conn)

    conn.close()

    logging.info("=" * 60)
    logging.info("HUD FMR ETL — COMPLETE")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()
