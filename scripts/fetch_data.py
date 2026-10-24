"""Download the raw 311 rows (and daily weather) that the dashboard is built from.

Pulls only the columns we need for the problem types we analyze, from Jan 2022
(the start of the Adams administration and of the current 311 problem taxonomy)
through today. Raw files land in data/raw/ and are NOT needed by the deployed app;
run scripts/build_metrics.py afterwards to produce the small aggregate files.

    python scripts/fetch_data.py

Set NYC_APP_TOKEN in your environment to avoid throttling (optional).
"""
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
START_YEAR = 2022
END_YEAR = 2026
PAGE = 200_000

# key -> SoQL filter on the "Problem" (complaint_type) / "Problem Detail" (descriptor) columns
PROBLEMS = {
    "heat": "complaint_type='HEAT/HOT WATER'",
    "pothole": "complaint_type='Street Condition' AND descriptor='Pothole'",
    "dumping": "complaint_type='Illegal Dumping'",
    "missed_collection": "complaint_type='Missed Collection'",
    "dirty": "complaint_type='Dirty Condition'",
    "snow": "complaint_type='Snow or Ice'",
    "homeless": "complaint_type='Homeless Person Assistance'",
}
COLS = "unique_key,created_date,closed_date,borough,status,open_data_channel_type"

HEADERS = {"X-App-Token": os.environ["NYC_APP_TOKEN"]} if os.environ.get("NYC_APP_TOKEN") else {}


def fetch(key, year):
    out = RAW / f"{key}_{year}.parquet"
    if out.exists() and year < END_YEAR:
        return f"{out.name} (cached)"
    where = f"{PROBLEMS[key]} AND created_date>='{year}-01-01' AND created_date<'{year + 1}-01-01'"
    frames, offset = [], 0
    while True:
        params = {"$select": COLS, "$where": where, "$order": "unique_key",
                  "$limit": PAGE, "$offset": offset}
        r = requests.get(URL, params=params, headers=HEADERS, timeout=600)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), dtype=str)
        frames.append(df)
        if len(df) < PAGE:
            break
        offset += PAGE
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(out, index=False)
    return f"{out.name}: {len(df):,} rows"


def fetch_all_311_monthly():
    """Total 311 volume by month and intake channel, aggregated server-side.

    One query per month: grouping on date_trunc_ym() over the whole table is very slow.
    """
    def one_month(start):
        end = start + pd.offsets.MonthBegin(1)
        params = {
            "$select": "open_data_channel_type as channel, count(*) as n",
            "$where": f"created_date>='{start:%Y-%m-%d}' AND created_date<'{end:%Y-%m-%d}'",
            "$group": "channel",
        }
        r = requests.get(URL, params=params, headers=HEADERS, timeout=300)
        r.raise_for_status()
        return pd.read_csv(io.StringIO(r.text)).assign(month=start)

    months = pd.date_range(f"{START_YEAR}-01-01", pd.Timestamp.today(), freq="MS")
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one_month, months))
    pd.concat(frames).to_parquet(RAW / "all_311_monthly.parquet", index=False)
    return "all_311_monthly.parquet"


def fetch_weather():
    """Daily Central Park weather from the Open-Meteo historical archive (no key needed)."""
    params = {
        "latitude": 40.78, "longitude": -73.97,
        "start_date": f"{START_YEAR - 1}-10-01", "end_date": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "daily": "temperature_2m_min,temperature_2m_mean,snowfall_sum,precipitation_sum",
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
        "timezone": "America/New_York",
    }
    r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=120)
    r.raise_for_status()
    pd.DataFrame(r.json()["daily"]).to_parquet(RAW / "weather_daily.parquet", index=False)
    return "weather_daily.parquet"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = [(k, y) for k in PROBLEMS for y in range(START_YEAR, END_YEAR + 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, k, y) for k, y in jobs]
        futures += [pool.submit(fetch_all_311_monthly), pool.submit(fetch_weather)]
        for f in futures:
            print(f.result(), flush=True)


if __name__ == "__main__":
    sys.exit(main())
