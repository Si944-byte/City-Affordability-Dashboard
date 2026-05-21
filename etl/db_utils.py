"""
db_utils.py
Shared database connection utility for City Affordability Dashboard ETL.
Server: DESKTOP-1CRNFTD | Database: CityAffordability | SQL Server 2019
"""

import pyodbc
import logging

# ----------------------------------------------------------------
# Connection string
# ----------------------------------------------------------------
CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER="Your Server Name here";"
    "DATABASE=CityAffordability;"
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
        print(f"           Database  : {row.db}")
        print(f"           Server time: {row.server_time}")
        conn.close()
    except Exception as e:
        print(f"[db_utils] Connection test FAILED: {e}")


if __name__ == "__main__":
    test_connection()
