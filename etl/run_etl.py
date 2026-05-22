"""
run_etl.py
Master ETL runner for City Affordability Dashboard.
Runs all data pipelines in order. Stops on first failure.

Schedule: Monthly via Windows Task Scheduler (run_etl.bat)
Log:      logs/run_etl.log

Usage:
    python run_etl.py
"""

import sys
import os
import logging
import importlib
from pathlib import Path
from datetime import datetime

# ----------------------------------------------------------------
# Project root — all paths are relative to this file
# ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Add project root to path so ETL modules are importable
sys.path.insert(0, str(BASE_DIR))

# ----------------------------------------------------------------
# Master log
# ----------------------------------------------------------------
LOG_FILE = LOG_DIR / "run_etl.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# ----------------------------------------------------------------
# ETL pipeline definitions
# Add new ETL scripts here as the project grows
# ----------------------------------------------------------------
PIPELINES = [
    ("Zillow ZORI (Rent)",          "etl_zillow_zori",    "main"),
    ("Zillow ZHVI (Home Prices)",   "etl_zillow_zhvi",    "main"),
    ("Census ACS (Income)",         "etl_census_acs",     "main"),
    ("BLS LAUS (Unemployment)",     "etl_bls_laus",       "main"),
    ("FRED Mortgage Rates",         "etl_fred_mortgage",  "main"),
    ("HUD Fair Market Rents",       "etl_hud_fmr",        "main"),
]


def run_all():
    start_time = datetime.now()

    logging.info("=" * 60)
    logging.info("CITY AFFORDABILITY ETL — MASTER RUNNER")
    logging.info(f"Start time     : {start_time}")
    logging.info(f"Pipelines      : {len(PIPELINES)}")
    logging.info(f"Project root   : {BASE_DIR}")
    logging.info("=" * 60)

    results = []

    for pipeline_name, module_name, func_name in PIPELINES:
        logging.info(f"\n--- Starting: {pipeline_name} ---")
        step_start = datetime.now()

        try:
            module    = importlib.import_module(module_name)
            main_func = getattr(module, func_name)
            main_func()

            duration = (datetime.now() - step_start).seconds
            logging.info(f"✓ PASSED: {pipeline_name} ({duration}s)")
            results.append((pipeline_name, "PASSED", duration, None))

        except Exception as e:
            duration = (datetime.now() - step_start).seconds
            logging.error(f"✗ FAILED: {pipeline_name} — {e}")
            results.append((pipeline_name, "FAILED", duration, str(e)))
            logging.error("Pipeline halted. Fix the error above and re-run.")
            break

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    total_duration = (datetime.now() - start_time).seconds

    logging.info("\n" + "=" * 60)
    logging.info("ETL RUN SUMMARY")
    logging.info("=" * 60)

    all_passed = True
    for name, status, dur, error in results:
        symbol = "✓" if status == "PASSED" else "✗"
        logging.info(f"  {symbol} {name:<35} {status:<8} ({dur}s)")
        if status == "FAILED":
            logging.info(f"    Error: {error}")
            all_passed = False

    ran_names = [r[0] for r in results]
    for name, _, _ in PIPELINES:
        if name not in ran_names:
            logging.info(f"  - {name:<35} SKIPPED")

    logging.info(f"\nTotal duration : {total_duration}s")
    logging.info(f"Completed at   : {datetime.now()}")

    if all_passed:
        logging.info("STATUS: ALL PIPELINES PASSED ✓")
    else:
        logging.info("STATUS: PIPELINE FAILED — CHECK LOGS ✗")
        sys.exit(1)


if __name__ == "__main__":
    run_all()
