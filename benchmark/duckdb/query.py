"""
DuckDB engine adapter for the benchmark runner.

Can query:
  - S3 directly via httpfs:  S3_BUCKET=<bucket> python query.py
  - Local CSV fallback:      CSV_PATH=data_setup/city_temperatures.parquet python query.py
"""
import os
import time
import duckdb

# ---------------------------------------------------------------------------
# Connection setup
# ---------------------------------------------------------------------------

def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    bucket = os.environ.get("S3_BUCKET")

    if bucket:
        region = os.environ.get("AWS_REGION", "us-east-1")
        con.execute(f"SET s3_region='{region}';")
        # Use instance profile / env-var credentials automatically
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"""
            CREATE OR REPLACE VIEW city_temperatures AS
            SELECT * FROM read_csv_auto(
                's3://{bucket}/raw/*/temperatures.csv',
                hive_partitioning = true
            );
        """)
    else:
        csv_path = os.environ.get("CSV_PATH", "data_setup/city_temperature.csv")
        con.execute(f"""
            CREATE OR REPLACE VIEW city_temperatures AS
            SELECT * FROM read_csv_auto('{csv_path}');
        """)

    return con


# ---------------------------------------------------------------------------
# Query runner
# ---------------------------------------------------------------------------

def run_query(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list, float]:
    """Returns (rows, elapsed_ms)."""
    start = time.perf_counter()
    rows = con.execute(sql).fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return rows, elapsed_ms


# ---------------------------------------------------------------------------
# Standalone smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    con = get_connection()
    sql = "SELECT region, ROUND(AVG(temperature_c), 2) AS avg_c FROM city_temperatures GROUP BY region ORDER BY 2 DESC"
    rows, ms = run_query(con, sql)
    print(f"{'Region':<20} {'Avg °C':>8}")
    print("-" * 30)
    for region, avg in rows:
        print(f"{str(region):<20} {avg:>8.2f}")
    print(f"\nElapsed: {ms:.1f} ms")
