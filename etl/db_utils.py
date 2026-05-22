"""
db_utils.py
Shared database connection utility for City Affordability Dashboard ETL.

Configuration:
  Set environment variables or update .env file:
  - SQL_SERVER   : SQL Server instance name (default: localhost)
  - SQL_DATABASE : Database name (default: CityAffordability)

  For Windows Authentication (default): no credentials needed.
  For SQL Authentication: set SQL_USERNAME and SQL_PASSWORD.
"""

import os
import pyodbc
import logging
from pathlib import Path
from dotenv import load_dotenv

# ----------------------------------------------------------------
# Load .env file if present
# ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ----------------------------------------------------------------
# Connection configuration — reads from environment variables
# Falls back to defaults if not set
# ----------------------------------------------------------------
SQL_SERVER   = os.getenv("SQL_SERVER",   "localhost")
SQL_DATABASE = os.getenv("SQL_DATABASE", "CityAffordability")
SQL_USERNAME = os.getenv("SQL_USERNAME", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")

# Build connection string
if SQL_USERNAME and SQL_PASSWORD:
    # SQL Server Authentication
    CONNECTION_STRING = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};"
        f"PWD={SQL_PASSWORD};"
    )
else:
    # Windows Authentication (default for local SQL Server)
    CONNECTION_STRING = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
    )


def get_connection():
    """
    Returns a live pyodbc connection.
    Always call conn.close() when done, or use as context manager.
    """
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except pyodbc.Error as e:
        logging.error(f"[db_utils] Connection failed: {e}")
        raise


def test_connection():
    """
    Quick connectivity check. Run this script directly to verify.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME() AS db, GETDATE() AS server_time;")
        row = cursor.fetchone()
        print(f"[db_utils] Connected successfully.")
        print(f"           Database   : {row.db}")
        print(f"           Server time: {row.server_time}")
        print(f"           Server     : {SQL_SERVER}")
        conn.close()
    except Exception as e:
        print(f"[db_utils] Connection test FAILED: {e}")


if __name__ == "__main__":
    test_connection()
