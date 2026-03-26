import io
import logging
import os
import pandas as pd
import numpy as np
from datetime import timedelta
import boto3

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Season detection
# ---------------------------------------------------------------------------

SOUTHERN_HEMISPHERE_REGIONS = {"Australia", "South America"}

SEASON_AMPLITUDE = {
    "Winter": 4.0,
    "Spring": 7.0,
    "Summer": 10.0,
    "Autumn": 6.0,
}

def get_season(month: int, southern: bool = False) -> str:
    nh = {12: "Winter", 1: "Winter", 2: "Winter",
          3: "Spring",  4: "Spring", 5: "Spring",
          6: "Summer",  7: "Summer", 8: "Summer",
          9: "Autumn", 10: "Autumn", 11: "Autumn"}[month]
    if not southern:
        return nh
    return {"Winter": "Summer", "Summer": "Winter",
            "Spring": "Autumn",  "Autumn": "Spring"}[nh]


# ---------------------------------------------------------------------------
# Sinusoidal intra-day model
# ---------------------------------------------------------------------------

def sinusoidal_temp(t_avg: float, amplitude: float, hour: float) -> float:
    """
    T(h) = T_avg + A * sin(2π * (h - 8) / 24)

    Phase shift of 8 h places:
      peak  at h = 8 + 6  = 14:00  (2 PM  – afternoon solar maximum)
      trough at h = 8 - 6  = 02:00  (2 AM  – pre-dawn minimum)
    """
    return t_avg + amplitude * np.sin(2 * np.pi * (hour - 8) / 24)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def delete_s3_prefix(s3_client, bucket: str, prefix: str) -> int:
    """Delete all objects under prefix. Returns count of deleted objects."""
    deleted = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue
        s3_client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
        )
        deleted += len(objects)
    return deleted


def write_date_partition(s3_client, bucket: str, city: str, date_str: str, rows: list[dict]) -> str:
    """Write rows for one date to s3://bucket/raw/city=<city>/date=<date>/temperatures.csv"""
    key = f"raw/city={city}/date={date_str}/temperatures.csv"
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(), ContentType="text/csv")
    return key


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def load_dataframe() -> pd.DataFrame:
    """Load source CSV from S3 or local fallback."""
    bucket    = os.environ.get("S3_BUCKET")
    input_key = os.environ.get("S3_INPUT_KEY", "city_temperature.csv")

    if bucket:
        log.info("Loading s3://%s/%s", bucket, input_key)
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=input_key)
        df  = pd.read_csv(io.BytesIO(obj["Body"].read()), low_memory=False)
    else:
        local_path = os.environ.get("CSV_PATH", "city_temperature.csv")
        log.info("Loading local file: %s", local_path)
        df = pd.read_csv(local_path, low_memory=False)

    df = df[df["AvgTemperature"] > -99]
    log.info("Loaded %d rows after filtering missing values", len(df))
    return df


# ---------------------------------------------------------------------------
# Main extrapolation
# ---------------------------------------------------------------------------

def extrapolate_30min_readings(
    df: pd.DataFrame,
    city: str,
    limit_days: int,
) -> int:
    """
    Generate 30-min temperature readings for one city and write to S3
    partitioned by city and date.

    Returns total number of readings written.

    Technique
    ---------
    T(slot) = lerp(T_avg[day], T_avg[day+1], slot/48)
              + A_season * sin(2π * (hour - 8) / 24)
    """
    log.info("[%s] Starting extrapolation for %d days", city, limit_days)

    city_df = df[df["City"] == city].copy()
    city_df["Date"] = pd.to_datetime(city_df[["Year", "Month", "Day"]])
    city_df = city_df.sort_values("Date").reset_index(drop=True)
    city_df = city_df.head(limit_days + 1).reset_index(drop=True)

    region   = city_df["Region"].iloc[0]
    southern = region in SOUTHERN_HEMISPHERE_REGIONS

    bucket    = os.environ.get("S3_BUCKET")
    s3_client = boto3.client("s3") if bucket else None

    # Delete existing city partition before writing fresh data
    if bucket:
        city_prefix = f"raw/city={city}/"
        deleted = delete_s3_prefix(s3_client, bucket, city_prefix)
        if deleted:
            log.info("[%s] Deleted %d existing object(s) under s3://%s/%s",
                     city, deleted, bucket, city_prefix)

    slots_per_day  = 48
    total_written  = 0

    for day_i in range(limit_days):
        row      = city_df.iloc[day_i]
        row_next = city_df.iloc[day_i + 1]

        t_today    = row["AvgTemperature"]
        t_tomorrow = row_next["AvgTemperature"]
        base_date  = row["Date"]
        date_str   = base_date.strftime("%Y-%m-%d")
        season     = get_season(base_date.month, southern)
        amplitude  = SEASON_AMPLITUDE[season]

        daily_readings = []
        for slot in range(slots_per_day):
            frac   = slot / slots_per_day
            t_base = t_today + frac * (t_tomorrow - t_today)
            hour   = slot * 0.5
            temp_f = sinusoidal_temp(t_base, amplitude, hour)
            temp_c = (temp_f - 32) * 5 / 9

            daily_readings.append({
                "timestamp":     (base_date + timedelta(minutes=30 * slot)).strftime("%Y-%m-%d %H:%M:%S"),
                "region":        row["Region"],
                "country":       row["Country"],
                "state":         row["State"] if pd.notna(row["State"]) else "",
                "city":          city,
                "season":        season,
                "temperature_f": round(temp_f, 4),
                "temperature_c": round(temp_c, 4),
            })

        if bucket:
            key = write_date_partition(s3_client, bucket, city, date_str, daily_readings)
            log.info("[%s] %s → s3://%s/%s (%d rows)", city, date_str, bucket, key, len(daily_readings))
        else:
            col = f"{'Timestamp':<22} {'City':<12} {'Season':<8} {'Temp °F':>9} {'Temp °C':>9}"
            print(col)
            print("-" * len(col))
            for r in daily_readings:
                print(
                    f"{r['timestamp']:<22} {r['city']:<12} {r['season']:<8}"
                    f" {r['temperature_f']:>9.2f} {r['temperature_c']:>9.2f}"
                )

        total_written += len(daily_readings)

    log.info("[%s] Done — %d total readings written", city, total_written)
    return total_written


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _df = load_dataframe()

    city_days = (
        _df.groupby("City").size()
        .rename("days")
        .reset_index()
        .query("days >= 2")
    )
    log.info("Processing %d cities", len(city_days))

    grand_total = 0
    for _, row in city_days.iterrows():
        city_name = row["City"]
        limit     = int(row["days"]) - 1
        grand_total += extrapolate_30min_readings(df=_df, city=city_name, limit_days=limit)

    log.info("Grand total 30-min readings across all cities: %d", grand_total)
