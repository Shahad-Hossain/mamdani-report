"""Turn the raw 311 pulls into the small aggregate tables the dashboard reads.

    python scripts/build_metrics.py

Reads data/raw/*.parquet (from fetch_data.py) and writes data/*.csv. Only the CSVs
are needed to deploy the app.

Fairness rules used throughout:
* Compare the SAME calendar window across years (seasonality is huge in 311 data).
* "Closed within N days" only counts tickets at least N days old at the snapshot,
  so recent tickets that simply haven't had time to close don't drag 2026 down.
* Every share is computed from closed_date - created_date, so a 2023 ticket and a
  2026 ticket are judged against the same clock.
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
MAMDANI_START = pd.Timestamp("2026-01-01")
BOROUGHS = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]

QOL = {
    "pothole": "Potholes",
    "dumping": "Illegal dumping",
    "missed_collection": "Missed trash collection",
    "dirty": "Dirty sidewalk / street",
    "snow": "Snow or ice",
}


def load(key):
    df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(RAW / f"{key}_*.parquet")))])
    df["created"] = pd.to_datetime(df["created_date"])
    df["closed"] = pd.to_datetime(df["closed_date"])
    df["days"] = (df["closed"] - df["created"]).dt.total_seconds() / 86400
    # A handful of tickets close before they open; treat them as data errors.
    df = df[~(df["days"] < 0)]
    df["borough"] = df["borough"].where(df["borough"].isin(BOROUGHS), "UNSPECIFIED")
    return df


def with_citywide(df):
    """Duplicate rows under borough='CITYWIDE' so every table can be filtered the same way."""
    return pd.concat([df, df.assign(borough="CITYWIDE")], ignore_index=True)


def closed_within(n, days, snapshot, created):
    """Share closed within n days, among tickets old enough to have had n days."""
    eligible = created <= snapshot - pd.Timedelta(days=n)
    if eligible.sum() == 0:
        return np.nan
    return ((days <= n) & eligible).sum() / eligible.sum()


def season_of(dates):
    """Heating season label: Oct 2025 - May 2026 is '2025-26'."""
    start = dates.dt.year.where(dates.dt.month >= 10, dates.dt.year - 1)
    return start.astype(str) + "-" + (start + 1).astype(str).str[-2:]


def weather():
    w = pd.read_parquet(RAW / "weather_daily.parquet")
    w["date"] = pd.to_datetime(w["time"])
    w = w.rename(columns={"temperature_2m_min": "tmin", "temperature_2m_mean": "tmean",
                          "snowfall_sum": "snow_cm", "precipitation_sum": "precip_in"})
    return w[["date", "tmin", "tmean", "snow_cm", "precip_in"]]


def build_winters(w):
    winter = w[w["date"].dt.month.isin([11, 12, 1, 2, 3])].copy()
    winter["season"] = season_of(winter["date"])
    out = winter.groupby("season").agg(
        days_below_20=("tmin", lambda s: int((s <= 20).sum())),
        days_below_10=("tmin", lambda s: int((s <= 10).sum())),
        snow_in=("snow_cm", lambda s: round(s.sum() / 2.54, 1)),
        coldest_f=("tmin", "min"),
    ).reset_index()
    out = out[out["season"] >= "2021-22"]
    out.to_csv(OUT / "winters.csv", index=False)


def build_heat(w):
    h = load("heat")
    snap = h["created"].max()
    h["date"] = h["created"].dt.normalize()
    h = with_citywide(h)

    daily = h.groupby(["borough", "date"]).apply(
        lambda g: pd.Series({
            "complaints": len(g),
            "closed_7d": closed_within(7, g["days"], snap, g["created"]),
            "still_open": int(g["closed"].isna().sum()),
        }), include_groups=False).reset_index()
    daily = daily.merge(w, on="date", how="left")
    daily["season"] = season_of(daily["date"])
    daily["mayor"] = np.where(daily["date"] >= MAMDANI_START, "Mamdani", "Adams")
    daily = daily[daily["date"].dt.month.isin([10, 11, 12, 1, 2, 3, 4, 5])]
    daily.to_csv(OUT / "heat_daily.csv", index=False)

    # Same-temperature comparison: heating months only, citywide days.
    cw = daily[(daily["borough"] == "CITYWIDE") & daily["date"].dt.month.isin([11, 12, 1, 2, 3])].copy()
    cw["temp_band"] = pd.cut(cw["tmin"], [-50, 10, 20, 30, 40, 100],
                             labels=["Below 10°F", "10–20°F", "20–30°F", "30–40°F", "Above 40°F"])
    bands = cw.groupby(["temp_band", "mayor"], observed=True).agg(
        days=("complaints", "size"), avg_complaints=("complaints", "mean"),
        closed_7d=("closed_7d", "mean")).reset_index()
    bands.to_csv(OUT / "heat_temp_bands.csv", index=False)

    # Jan 1 - Sep 30 of each year, by borough: how many tickets were left hanging?
    ytd = h[(h["created"].dt.month <= 9)].copy()
    ytd["year"] = ytd["created"].dt.year
    yearly = ytd.groupby(["borough", "year"]).apply(
        lambda g: pd.Series({
            "complaints": len(g),
            "closed_7d": closed_within(7, g["days"], snap, g["created"]),
            "open_after_30d": int(((g["days"] > 30) | g["closed"].isna()).sum()),
            "median_days": g["days"].median(),
        }), include_groups=False).reset_index()
    yearly["open_after_30d_pct"] = yearly["open_after_30d"] / yearly["complaints"]
    yearly.to_csv(OUT / "heat_yearly.csv", index=False)


def build_homeless(w):
    hm = load("homeless")
    hm["date"] = hm["created"].dt.normalize()
    hm = with_citywide(hm)
    daily = hm.groupby(["borough", "date"]).size().rename("complaints").reset_index()
    full = pd.MultiIndex.from_product(
        [daily["borough"].unique(), pd.date_range("2025-12-01", "2026-03-15")], names=["borough", "date"])
    daily = daily.set_index(["borough", "date"]).reindex(full, fill_value=0).reset_index()
    daily = daily.merge(w, on="date", how="left")
    daily.to_csv(OUT / "homeless_daily.csv", index=False)


def build_qol():
    monthly, yearly = [], []
    for key, label in QOL.items():
        df = load(key)
        snap = df["created"].max()
        df = with_citywide(df)
        df["month"] = df["created"].dt.to_period("M")

        for boro, g in df.groupby("borough"):
            created = g.groupby("month").size()
            closed = g.dropna(subset=["closed"]).groupby(g["closed"].dt.to_period("M")).size()
            months = pd.period_range("2022-01", snap.to_period("M"), freq="M")
            m = pd.DataFrame({"created": created.reindex(months, fill_value=0),
                              "closed": closed.reindex(months, fill_value=0)})
            # Backlog at month end = opened by then and not yet closed by then.
            ends = months.to_timestamp(how="end")
            c = np.sort(g["created"].values)
            cl = np.sort(g["closed"].dropna().values)
            m["open_backlog"] = [np.searchsorted(c, e, side="right") - np.searchsorted(cl, e, side="right")
                                 for e in ends.values]
            m["closed_7d"] = g.groupby("month").apply(
                lambda x: closed_within(7, x["days"], snap, x["created"]),
                include_groups=False).reindex(months)
            m["median_days"] = g.groupby("month")["days"].median().reindex(months)
            m = m.reset_index(names="month")
            m["month"] = m["month"].dt.to_timestamp()
            m["borough"], m["problem"] = boro, label
            monthly.append(m)

        # Same window every year: tickets opened Jan 1 - Aug 31.
        jan_aug = df[df["created"].dt.month <= 8].copy()
        jan_aug["year"] = jan_aug["created"].dt.year
        y = jan_aug.groupby(["borough", "year"]).apply(
            lambda x: pd.Series({
                "complaints": len(x),
                "closed_7d": closed_within(7, x["days"], snap, x["created"]),
                "closed_30d": closed_within(30, x["days"], snap, x["created"]),
                "median_days": x["days"].median(),
            }), include_groups=False).reset_index()
        y["problem"] = label
        yearly.append(y)

    pd.concat(monthly).to_csv(OUT / "qol_monthly.csv", index=False)
    pd.concat(yearly).to_csv(OUT / "qol_yearly.csv", index=False)


def build_all_311():
    a = pd.read_parquet(RAW / "all_311_monthly.parquet")
    a["month"] = pd.to_datetime(a["month"])
    a["channel"] = a["channel"].fillna("UNKNOWN").str.title()
    a = a[a["month"] < a["month"].max()]  # drop the partial current month
    a.to_csv(OUT / "all_311_monthly.csv", index=False)


def main():
    w = weather()
    build_winters(w)
    build_heat(w)
    build_homeless(w)
    build_qol()
    build_all_311()
    for f in sorted(OUT.glob("*.csv")):
        print(f"{f.name:28} {f.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    main()
