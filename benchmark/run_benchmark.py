"""
Performance benchmark runner.

Usage:
    python benchmark/run_benchmark.py --engine duckdb
    python benchmark/run_benchmark.py --engine athena
    python benchmark/run_benchmark.py --engine trino
    python benchmark/run_benchmark.py --engine all        # compare side-by-side

Environment variables:
    S3_BUCKET      - S3 bucket holding raw/city=*/temperatures.csv
    AWS_REGION     - AWS region (default: us-east-1)
    TRINO_HOST     - Trino coordinator host (default: localhost)
    TRINO_PORT     - Trino coordinator port (default: 8080)
    ATHENA_WG      - Athena workgroup name (default: city-temperature)
    ATHENA_DB      - Glue database name    (default: city_temperature)
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

QUERY_DIR = Path(__file__).parent / "queries"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Load SQL queries from files
# ---------------------------------------------------------------------------

def load_queries() -> dict[str, str]:
    return {
        p.stem: p.read_text()
        for p in sorted(QUERY_DIR.glob("*.sql"))
    }

# ---------------------------------------------------------------------------
# Engine adapters
# ---------------------------------------------------------------------------

def run_duckdb(queries: dict[str, str]) -> dict[str, float]:
    import duckdb
    from benchmark.duckdb.query import get_connection, run_query
    con = get_connection()
    timings = {}
    for name, sql in queries.items():
        _, ms = run_query(con, sql)
        timings[name] = ms
    return timings


def run_athena(queries: dict[str, str]) -> dict[str, float]:
    import boto3

    region  = os.environ.get("AWS_REGION", "us-east-1")
    bucket  = os.environ["S3_BUCKET"]
    wg      = os.environ.get("ATHENA_WG", "city-temperature")
    db      = os.environ.get("ATHENA_DB", "city_temperature")
    client  = boto3.client("athena", region_name=region)
    timings = {}

    for name, sql in queries.items():
        start = time.perf_counter()
        resp = client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": db},
            WorkGroup=wg,
        )
        qid = resp["QueryExecutionId"]

        # Poll until done
        while True:
            status = client.get_query_execution(QueryExecutionId=qid)
            state  = status["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)

        if state != "SUCCEEDED":
            raise RuntimeError(f"Athena query {name!r} ended with state {state}")

        elapsed_ms = (time.perf_counter() - start) * 1000
        # Subtract Athena's own reported engine execution time for fair comparison
        engine_ms = status["QueryExecution"]["Statistics"].get(
            "EngineExecutionTimeInMillis", elapsed_ms
        )
        timings[name] = float(engine_ms)

    return timings


def run_trino(queries: dict[str, str]) -> dict[str, float]:
    import trino  # pip install trino

    host    = os.environ.get("TRINO_HOST", "localhost")
    port    = int(os.environ.get("TRINO_PORT", "8080"))
    db      = os.environ.get("ATHENA_DB", "city_temperature")
    conn    = trino.dbapi.connect(host=host, port=port, user="benchmark",
                                  catalog="hive", schema=db)
    cursor  = conn.cursor()
    timings = {}

    for name, sql in queries.items():
        start = time.perf_counter()
        cursor.execute(sql)
        cursor.fetchall()
        timings[name] = (time.perf_counter() - start) * 1000

    return timings

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

ENGINE_RUNNERS = {
    "duckdb": run_duckdb,
    "athena": run_athena,
    "trino":  run_trino,
}


def print_table(results: dict[str, dict[str, float]]) -> None:
    engines = list(results.keys())
    queries = list(next(iter(results.values())).keys())

    col_w = max(len(q) for q in queries) + 2
    eng_w = 12

    header = f"{'Query':<{col_w}}" + "".join(f"{e:>{eng_w}}" for e in engines)
    print("\n" + header)
    print("-" * len(header))

    for q in queries:
        row = f"{q:<{col_w}}"
        for e in engines:
            ms = results[e].get(q)
            row += f"{ms:>{eng_w - 3}.1f} ms" if ms is not None else f"{'N/A':>{eng_w}}"
        print(row)

    print()


def save_results(results: dict[str, dict[str, float]]) -> None:
    ts   = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"benchmark_{ts}.json"
    path.write_text(json.dumps({"timestamp": ts, "results": results}, indent=2))
    print(f"Results saved → {path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Query engine benchmark")
    parser.add_argument(
        "--engine",
        choices=[*ENGINE_RUNNERS.keys(), "all"],
        default="duckdb",
        help="Engine to benchmark (default: duckdb)",
    )
    args = parser.parse_args()

    queries = load_queries()
    engines = list(ENGINE_RUNNERS.keys()) if args.engine == "all" else [args.engine]

    results = {}
    for engine in engines:
        print(f"Running {engine}…")
        results[engine] = ENGINE_RUNNERS[engine](queries)

    print_table(results)
    save_results(results)


if __name__ == "__main__":
    main()
