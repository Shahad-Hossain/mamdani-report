# Is Mayor Mamdani doing a good job? — a NYC 311 dashboard

A one-page Plotly Dash story that grades the Mamdani administration (Jan 2026 – present) against the
Adams years (2022–2025) on two questions:

1. **Extreme weather & life safety** – heat/hot-water complaints during the 2025–26 cold snap, how fast
   they were closed, and whether the 311→911 Code Blue reroute actually happened.
2. **Quality of life & neighborhood repairs** – potholes, illegal dumping, missed trash collection,
   dirty streets and snow/ice: are tickets closed faster, and is the backlog shrinking?

## Project layout

```
app.py                  the Dash app (all charts + narrative)
assets/style.css        page styling (Dash loads /assets automatically)
data/*.csv              small pre-aggregated tables the app reads  <- needed to deploy
scripts/fetch_data.py   downloads raw 311 rows + weather            (not needed to deploy)
scripts/build_metrics.py turns raw rows into data/*.csv             (not needed to deploy)
requirements.txt
```

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt pyarrow requests
python app.py                   # open http://127.0.0.1:8050
```

To refresh the data (≈2.7M rows, a few minutes):

```bash
python scripts/fetch_data.py
python scripts/build_metrics.py
```

## Method notes

* Source: NYC Open Data *311 Service Requests from 2020 to Present* (`erm2-nwe9`), where the
  "Complaint Type" column is now labeled **Problem**. Analysis starts in 2022 because 311 renamed its
  sanitation problem types in late 2021.
* Every year-over-year comparison uses the same calendar window (e.g. Jan–Aug vs Jan–Aug).
* "Closed within N days" only counts tickets at least N days old at the data snapshot, so recent
  tickets aren't penalized for not having had time to close.
* Weather: daily Central Park lows from the Open-Meteo historical archive.
* 311 closure ≠ repair. Agencies close tickets for many reasons, so these are service-responsiveness
  measures, not proof that problems were fixed.
