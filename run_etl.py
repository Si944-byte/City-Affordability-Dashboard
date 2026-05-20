"""
run_etl.py
Master ETL runner for City Affordability Dashboard.
Runs all 5 data pipelines in order. Stops on first failure.

Schedule: Monthly via Windows Task Scheduler
Log:      C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard\\logs\\run_etl.log

Project: City Affordability Dashboard
Path:    C:\\Users\\TJs PC\\OneDrive\\Desktop\\Projects\\City Dashboard
"""

import sys
import os
import logging
from datetime import datetime

PROJECT_DIR = r"C:\Users\TJs PC\OneDrive\Desktop\Projects\City Dashboard"
sys.path.insert(0, PROJECT_DIR)

# ----------------------------------------------------------------
# Master log — separate from individual ETL logs
# ----------------------------------------------------------------
LOG_FILE = os.path.join(PROJECT_DIR, "logs", "run_etl.log")
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
# ETL pipeline definitions (name, module, main function)
# ----------------------------------------------------------------
PIPELINES = [
    ("Zillow ZORI (Rent)",          "etl_zillow_zori",    "main"),
    ("Zillow ZHVI (Home Prices)",   "etl_zillow_zhvi",    "main"),
    ("Census ACS (Income)",         "etl_census_acs",     "main"),
    ("BLS LAUS (Unemployment)",     "etl_bls_laus",       "main"),
    ("FRED Mortgage Rates",         "etl_fred_mortgage",  "main"),
]


def run_all():
    start_time = datetime.now()

    logging.info("=" * 60)
    logging.info("CITY AFFORDABILITY ETL — MASTER RUNNER")
    logging.info(f"Start time: {start_time}")
    logging.info(f"Pipelines to run: {len(PIPELINES)}")
    logging.info("=" * 60)

    results = []

    for pipeline_name, module_name, func_name in PIPELINES:
        logging.info(f"\n--- Starting: {pipeline_name} ---")
        step_start = datetime.now()

        try:
            # Dynamically import and run each ETL module
            import importlib
            module = importlib.import_module(module_name)
            main_func = getattr(module, func_name)
            main_func()

            duration = (datetime.now() - step_start).seconds
            logging.info(f"✓ PASSED: {pipeline_name} ({duration}s)")
            results.append((pipeline_name, "PASSED", duration, None))

        except Exception as e:
            duration = (datetime.now() - step_start).seconds
            logging.error(f"✗ FAILED: {pipeline_name} — {e}")
            results.append((pipeline_name, "FAILED", duration, str(e)))

            # Stop on failure — don't load bad data downstream
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

    # Log any pipelines that didn't run due to earlier failure
    ran_names = [r[0] for r in results]
    for name, _, _ in PIPELINES:
        if name not in ran_names:
            logging.info(f"  - {name:<35} SKIPPED")

    logging.info(f"\nTotal duration: {total_duration}s")
    logging.info(f"Completed at:   {datetime.now()}")

    if all_passed:
        logging.info("STATUS: ALL PIPELINES PASSED ✓")
    else:
        logging.info("STATUS: PIPELINE FAILED — CHECK LOGS ✗")
        sys.exit(1)  # Non-zero exit so Task Scheduler knows it failed


if __name__ == "__main__":
    run_all()
