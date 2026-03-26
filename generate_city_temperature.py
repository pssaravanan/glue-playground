import io
import os
import pandas as pd
import numpy as np
from datetime import timedelta
import boto3

# ---------------------------------------------------------------------------
# Season detection
# ---------------------------------------------------------------------------

SOUTHERN_HEMISPHERE_REGIONS = {"Australia", "South America"}

# Diurnal amplitude (°F) – half the daily swing, varies by season
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
# Main extrapolation
# ---------------------------------------------------------------------------

def load_dataframe() -> pd.DataFrame:
    """
    Load the source CSV from S3 (when S3_BUCKET + S3_INPUT_KEY are set)
    or from a local path (CSV_PATH env var, default city_temperature.csv).
    """
    bucket    = os.environ.get("S3_BUCKET")
    input_key = os.environ.get("S3_INPUT_KEY", "city_temperature.csv")

    if bucket:
        print(f"Reading s3://{bucket}/{input_key} ...")
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=input_key)
        df  = pd.read_csv(io.BytesIO(obj["Body"].read()), low_memory=False)
    else:
        local_path = os.environ.get("CSV_PATH", "city_temperature.csv")
        print(f"Reading local file: {local_path} ...")
        df = pd.read_csv(local_path, low_memory=False)

    return df[df["AvgTemperature"] > -99]


def extrapolate_30min_readings(
    df: pd.DataFrame,
    city: str,
    limit_days: int,
) -> list[dict]:
    """
    Generate a 30-minute temperature series from daily average readings.

    Technique
    ---------
    For each 30-min slot within a day the baseline T_avg is linearly
    interpolated between that day's average and the *next* day's average
    (the "average between subsequent dates").  A season-aware sinusoidal
    diurnal curve is then added on top of that smoothed baseline.

        T(slot) = lerp(T_avg[day], T_avg[day+1], slot/48)
                  + A_season * sin(2π * (hour - 8) / 24)
    """
    df = df[df["City"] == city].copy()
    df["Date"] = pd.to_datetime(df[["Year", "Month", "Day"]])
    df = df.sort_values("Date").reset_index(drop=True)

    # Need limit_days + 1 rows so every day has a "next day" for blending
    df = df.head(limit_days + 1).reset_index(drop=True)

    region   = df["Region"].iloc[0]
    southern = region in SOUTHERN_HEMISPHERE_REGIONS

    readings = []
    slots_per_day = 48   # 24 h × 2

    for day_i in range(limit_days):
        row      = df.iloc[day_i]
        row_next = df.iloc[day_i + 1]

        t_today    = row["AvgTemperature"]
        t_tomorrow = row_next["AvgTemperature"]

        base_date = row["Date"]
        season    = get_season(base_date.month, southern)
        amplitude = SEASON_AMPLITUDE[season]

        for slot in range(slots_per_day):
            # Linear blend of today's and tomorrow's daily average
            # (smooth day boundary – no midnight temperature jump)
            frac   = slot / slots_per_day
            t_base = t_today + frac * (t_tomorrow - t_today)

            hour   = slot * 0.5                          # 0.0, 0.5, 1.0 … 23.5
            temp_f = sinusoidal_temp(t_base, amplitude, hour)
            temp_c = (temp_f - 32) * 5 / 9

            timestamp = base_date + timedelta(minutes=30 * slot)

            readings.append({
                "timestamp":     timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "region":        row["Region"],
                "country":       row["Country"],
                "state":         row["State"] if pd.notna(row["State"]) else "",
                "city":          city,
                "season":        season,
                "temperature_f": round(temp_f, 4),
                "temperature_c": round(temp_c, 4),
            })

    # ------------------------------------------------------------------
    # Write to S3 partitioned by city  (falls back to stdout if no bucket)
    # ------------------------------------------------------------------
    bucket = os.environ.get("S3_BUCKET")
    if bucket:
        s3_key = f"city={city}/temperatures.csv"
        csv_buffer = io.StringIO()
        pd.DataFrame(readings).to_csv(csv_buffer, index=False)
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv",
        )
        print(f"  Written {len(readings)} rows → s3://{bucket}/{s3_key}")
    else:
        col = f"{'Timestamp':<22} {'City':<12} {'Season':<8} {'Temp °F':>9} {'Temp °C':>9}"
        print(col)
        print("-" * len(col))
        for r in readings:
            print(
                f"{r['timestamp']:<22} {r['city']:<12} {r['season']:<8}"
                f" {r['temperature_f']:>9.2f} {r['temperature_c']:>9.2f}"
            )
        print(f"\nTotal 30-min readings: {len(readings)}")

    return readings


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Load CSV once from S3 (or local fallback)
    _df = load_dataframe()

    # days per city (need at least 2 rows: today + next-day for blending)
    city_days = (
        _df.groupby("City").size()
        .rename("days")
        .reset_index()
        .query("days >= 2")
    )

    all_readings = []
    for _, row in city_days.iterrows():
        city_name = row["City"]
        limit     = int(row["days"]) - 1

        print(f"\n=== {city_name} ({limit} days) ===")
        readings = extrapolate_30min_readings(
            df=_df,
            city=city_name,
            limit_days=limit,
        )
        all_readings.extend(readings)

    print(f"\n{'='*60}")
    print(f"Grand total 30-min readings across all cities: {len(all_readings)}")
