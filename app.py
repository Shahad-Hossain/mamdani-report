"""Is Mayor Mamdani doing a good job? A 311 data story.

Run locally:   python app.py   ->  http://127.0.0.1:8050
Deploy:        see README.md (Plotly Cloud or Render; `server` is the WSGI entry point)
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html
from plotly.subplots import make_subplots

DATA = Path(__file__).resolve().parent / "data"

# ---- palette (validated reference palette; Mamdani is always the highlighted series) ----
MAMDANI = "#2a78d6"
ADAMS = "#a8a69f"
ADAMS_DARK = "#52514e"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
GOOD, WARN, BAD = "#0ca30c", "#fab219", "#d03b3b"
COLD = "#86b6ef"
DIVERGING = [[0, "#d03b3b"], [0.5, "#f0efec"], [1, "#256abf"]]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# ---- data ----
winters = pd.read_csv(DATA / "winters.csv")
heat_daily = pd.read_csv(DATA / "heat_daily.csv", parse_dates=["date"])
heat_bands = pd.read_csv(DATA / "heat_temp_bands.csv")
heat_yearly = pd.read_csv(DATA / "heat_yearly.csv")
homeless = pd.read_csv(DATA / "homeless_daily.csv", parse_dates=["date"])
qol_monthly = pd.read_csv(DATA / "qol_monthly.csv", parse_dates=["month"])
qol_yearly = pd.read_csv(DATA / "qol_yearly.csv")
all_311 = pd.read_csv(DATA / "all_311_monthly.csv", parse_dates=["month"])

AS_OF = f"{qol_monthly['month'].max():%B %Y}"
BOROUGH_OPTIONS = [{"label": "All of NYC", "value": "CITYWIDE"}] + [
    {"label": b.title(), "value": b} for b in ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]]
PROBLEMS = ["Potholes", "Illegal dumping", "Missed trash collection", "Dirty sidewalk / street", "Snow or ice"]
REROUTE = (pd.Timestamp("2026-01-31"), pd.Timestamp("2026-02-12"))
TAKES_OFFICE = pd.Timestamp("2026-01-01")


def base_layout(fig, height=380, **kw):
    fig.update_layout(
        template="none", height=height, font=dict(family=FONT, size=13, color=INK_2),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, margin=dict(l=56, r=24, t=16, b=48),
        hoverlabel=dict(bgcolor="white", bordercolor=AXIS, font=dict(family=FONT, color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK_2)),
        **kw)
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickcolor=AXIS, tickfont=dict(color=MUTED), zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), zeroline=False)
    return fig


def pct(v):
    return f"{v:.0%}" if pd.notna(v) else "–"


# ======================================================================================
# Figures
# ======================================================================================

def fig_311_volume():
    """Total 311 volume: Jan–Sep of each year, so 2026 is compared like-for-like."""
    a = all_311[all_311["month"].dt.month <= 9].copy()
    a["year"] = a["month"].dt.year
    tot = a.groupby("year")["n"].sum()
    mix = a.pivot_table(index="year", columns="channel", values="n", aggfunc="sum").fillna(0)
    mix = mix.div(mix.sum(axis=1), axis=0)

    fig = make_subplots(rows=1, cols=2, column_widths=[0.45, 0.55], horizontal_spacing=0.12,
                        subplot_titles=("Total 311 requests, Jan–Sep (millions)", "How people reached 311 (share)"))
    fig.add_bar(x=tot.index.astype(str), y=tot.values / 1e6, row=1, col=1, showlegend=False,
                marker=dict(color=[MAMDANI if y == 2026 else ADAMS for y in tot.index], cornerradius=4),
                text=[f"{v / 1e6:.2f}M" for v in tot.values], textposition="outside",
                textfont=dict(color=INK_2), hovertemplate="%{x}: %{y:.2f}M requests<extra></extra>", cliponaxis=False)
    channel_colors = {"Online": "#2a78d6", "Mobile": "#1baf7a", "Phone": "#eb6834", "Unknown": "#c3c2b7", "Other": "#e87ba4"}
    for ch in [c for c in ["Online", "Mobile", "Phone", "Other", "Unknown"] if c in mix.columns]:
        fig.add_bar(x=mix.index.astype(str), y=mix[ch], name=ch, row=1, col=2,
                    marker=dict(color=channel_colors[ch], line=dict(color=SURFACE, width=2)),
                    hovertemplate=f"{ch}: %{{y:.0%}}<extra>%{{x}}</extra>")
    base_layout(fig, height=360, barmode="stack")
    fig.update_layout(legend=dict(x=0.56, y=1.12))
    fig.update_yaxes(tickformat=".0%", row=1, col=2)
    fig.update_yaxes(rangemode="tozero", row=1, col=1)
    fig.update_annotations(font=dict(size=13, color=INK), yshift=8)
    return fig


def fig_winters():
    w = winters.copy()
    fig = go.Figure(go.Bar(
        x=w["season"], y=w["days_below_20"],
        marker=dict(color=[MAMDANI if s == "2025-26" else ADAMS for s in w["season"]], cornerradius=4),
        text=w["days_below_20"], textposition="outside", textfont=dict(color=INK_2), cliponaxis=False,
        customdata=w[["days_below_10", "snow_in", "coldest_f"]],
        hovertemplate=("Winter %{x}<br>%{y} nights at or below 20°F<br>%{customdata[0]} nights at or below 10°F"
                       "<br>Snowfall: %{customdata[1]} in<br>Coldest night: %{customdata[2]:.0f}°F<extra></extra>")))
    base_layout(fig, height=300, yaxis_title="Nights ≤ 20°F (Nov–Mar)")
    return fig


def fig_heat_season(borough):
    """Daily heat complaints across each winter, aligned on the calendar."""
    d = heat_daily[(heat_daily["borough"] == borough) & heat_daily["date"].dt.month.isin([11, 12, 1, 2, 3])].copy()
    # Shift every season onto the 2025-26 calendar so the lines overlay.
    offset = d["season"].str[:4].astype(int) - 2025
    d["x"] = d["date"] - pd.to_timedelta(offset * 365, unit="D")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.06)
    for season, g in d.groupby("season"):
        is_now = season == "2025-26"
        fig.add_scatter(x=g["x"], y=g["complaints"], mode="lines", name=f"Winter {season}",
                        line=dict(color=MAMDANI if is_now else ADAMS, width=2.5 if is_now else 1.2),
                        opacity=1 if is_now else 0.7, row=1, col=1,
                        customdata=g["date"].dt.strftime("%b %d, %Y"),
                        hovertemplate="%{customdata}: %{y:,} heat complaints<extra></extra>")
        if is_now:
            fig.add_scatter(x=g["x"], y=g["tmin"], mode="lines", name="Overnight low, 2025-26", showlegend=False,
                            line=dict(color=COLD, width=1.5), fill="tozeroy", fillcolor="rgba(134,182,239,0.18)",
                            row=2, col=1, hovertemplate="Low: %{y:.0f}°F<extra></extra>")
    fig.add_vline(x=TAKES_OFFICE, line=dict(color=INK_2, width=1))
    fig.add_annotation(x=TAKES_OFFICE, y=1, yref="paper", text="Mamdani takes office", showarrow=False,
                       xanchor="left", xshift=4, font=dict(size=11, color=INK_2))
    base_layout(fig, height=440, hovermode="x unified")
    fig.update_yaxes(title_text="Heat complaints / day", row=1, col=1)
    fig.update_yaxes(title_text="Low °F", row=2, col=1)
    fig.update_xaxes(tickformat="%b", dtick="M1", row=2, col=1)
    return fig


def fig_heat_scatter():
    d = heat_daily[(heat_daily["borough"] == "CITYWIDE") & heat_daily["date"].dt.month.isin([11, 12, 1, 2, 3])]
    fig = go.Figure()
    for mayor, color, size in [("Adams", ADAMS, 6), ("Mamdani", MAMDANI, 8)]:
        g = d[d["mayor"] == mayor]
        fig.add_scatter(x=g["tmin"], y=g["complaints"], mode="markers", name=f"{mayor} winter days",
                        marker=dict(color=color, size=size, opacity=0.75 if mayor == "Adams" else 0.9,
                                    line=dict(color=SURFACE, width=1)),
                        customdata=g["date"].dt.strftime("%b %d, %Y"),
                        hovertemplate="%{customdata}<br>Low %{x:.0f}°F · %{y:,} complaints<extra></extra>")
    base_layout(fig, height=360, xaxis_title="Overnight low (°F)", yaxis_title="Heat complaints that day")
    return fig


def fig_heat_bands():
    """Dumbbell: % of heat tickets closed within 7 days, same temperature, each mayor."""
    b = heat_bands.pivot(index="temp_band", columns="mayor", values="closed_7d")
    order = ["Below 10°F", "10–20°F", "20–30°F", "30–40°F", "Above 40°F"]
    b = b.reindex(order)
    fig = go.Figure()
    for band, row in b.iterrows():
        fig.add_scatter(x=[row["Mamdani"], row["Adams"]], y=[band, band], mode="lines",
                        line=dict(color=AXIS, width=2), showlegend=False, hoverinfo="skip")
    for mayor, color in [("Adams", ADAMS_DARK), ("Mamdani", MAMDANI)]:
        fig.add_scatter(x=b[mayor], y=b.index, mode="markers", name=mayor,
                        marker=dict(color=color, size=12, line=dict(color=SURFACE, width=2)),
                        hovertemplate=f"{mayor}, %{{y}} nights: %{{x:.1%}} closed within 7 days<extra></extra>")
    base_layout(fig, height=320, xaxis_title="Heat tickets closed within 7 days")
    fig.update_layout(margin=dict(l=110))
    fig.update_yaxes(ticksuffix="  ")
    fig.update_xaxes(tickformat=".0%", range=[0.88, 1.0], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def fig_heat_open(borough):
    h = heat_yearly[heat_yearly["borough"] == borough]
    fig = go.Figure(go.Bar(
        x=h["year"].astype(str), y=h["open_after_30d"],
        marker=dict(color=[MAMDANI if y == 2026 else ADAMS for y in h["year"]], cornerradius=4),
        text=[f"{v:,.0f}" for v in h["open_after_30d"]], textposition="outside", cliponaxis=False,
        textfont=dict(color=INK_2), customdata=h[["complaints", "open_after_30d_pct"]],
        hovertemplate=("%{x}: %{y:,} of %{customdata[0]:,} heat tickets (Jan–Sep)<br>"
                       "took 30+ days or are still open (%{customdata[1]:.1%})<extra></extra>")))
    base_layout(fig, height=320, yaxis_title="Heat tickets open 30+ days")
    return fig


def fig_homeless(borough):
    d = homeless[homeless["borough"] == borough]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.06)
    fig.add_scatter(x=d["date"], y=d["complaints"], mode="lines", name="311 homeless-assistance requests",
                    line=dict(color=MAMDANI, width=2), row=1, col=1,
                    hovertemplate="%{x|%b %d}: %{y} requests<extra></extra>")
    fig.add_scatter(x=d["date"], y=d["tmin"], mode="lines", showlegend=False, line=dict(color=COLD, width=1.5),
                    fill="tozeroy", fillcolor="rgba(134,182,239,0.18)", row=2, col=1,
                    hovertemplate="Low: %{y:.0f}°F<extra></extra>")
    for r in (1, 2):
        fig.add_vrect(x0=REROUTE[0], x1=REROUTE[1], fillcolor="rgba(11,11,11,0.06)", line_width=0, row=r, col=1)
    fig.add_annotation(x=REROUTE[0] + (REROUTE[1] - REROUTE[0]) / 2, y=1, yref="paper", showarrow=False,
                       text="311 calls rerouted<br>to 911 (Code Blue)", font=dict(size=11, color=INK_2), yanchor="top")
    base_layout(fig, height=380, hovermode="x unified")
    fig.update_yaxes(title_text="Requests / day", row=1, col=1)
    fig.update_yaxes(title_text="Low °F", row=2, col=1)
    return fig


def fig_qol_dumbbell(borough):
    y = qol_yearly[(qol_yearly["borough"] == borough) & qol_yearly["year"].isin([2025, 2026])]
    p = y.pivot(index="problem", columns="year", values="closed_7d").reindex(PROBLEMS[::-1]).dropna()
    fig = go.Figure()
    for prob, row in p.iterrows():
        better = row[2026] >= row[2025]
        fig.add_scatter(x=[row[2025], row[2026]], y=[prob, prob], mode="lines", showlegend=False,
                        line=dict(color=AXIS, width=2), hoverinfo="skip")
        fig.add_annotation(x=row[2026], y=prob, text=f"{(row[2026] - row[2025]) * 100:+.0f} pts",
                           showarrow=False, xshift=30 if better else -30,
                           font=dict(size=12, color="#006300" if better else BAD))
    fig.add_scatter(x=p[2025], y=p.index, mode="markers", name="2025 (Adams)",
                    marker=dict(color=ADAMS_DARK, size=12, line=dict(color=SURFACE, width=2)),
                    hovertemplate="2025 · %{y}: %{x:.0%} closed in 7 days<extra></extra>")
    fig.add_scatter(x=p[2026], y=p.index, mode="markers", name="2026 (Mamdani)",
                    marker=dict(color=MAMDANI, size=12, line=dict(color=SURFACE, width=2)),
                    hovertemplate="2026 · %{y}: %{x:.0%} closed in 7 days<extra></extra>")
    lo = max(0, min(p.min().min() - 0.08, 0.9))
    base_layout(fig, height=320, xaxis_title="Tickets opened Jan–Aug that were closed within 7 days")
    fig.update_layout(margin=dict(l=180))
    fig.update_xaxes(tickformat=".0%", range=[lo, 1.04], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK_2))
    return fig


def fig_qol_trend(borough, problem):
    m = qol_monthly[(qol_monthly["borough"] == borough) & (qol_monthly["problem"] == problem)]
    m = m[m["month"] < m["month"].max()]  # drop partial month
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=("New tickets vs. tickets closed, per month", "Open backlog at month end"))
    fig.add_scatter(x=m["month"], y=m["created"], name="Opened", mode="lines",
                    line=dict(color=INK_2, width=2), row=1, col=1, hovertemplate="Opened: %{y:,}<extra></extra>")
    fig.add_scatter(x=m["month"], y=m["closed"], name="Closed", mode="lines",
                    line=dict(color=MAMDANI, width=2), row=1, col=1, hovertemplate="Closed: %{y:,}<extra></extra>")
    fig.add_scatter(x=m["month"], y=m["open_backlog"], name="Backlog", mode="lines", showlegend=False,
                    line=dict(color=MAMDANI, width=2), fill="tozeroy", fillcolor="rgba(42,120,214,0.15)",
                    row=2, col=1, hovertemplate="Still open: %{y:,}<extra></extra>")
    for r in (1, 2):
        fig.add_vrect(x0=TAKES_OFFICE, x1=m["month"].max() + pd.offsets.MonthEnd(1),
                      fillcolor="rgba(42,120,214,0.06)", line_width=0, row=r, col=1)
    fig.add_annotation(x=TAKES_OFFICE, y=1.0, yref="paper", text="Mamdani era", showarrow=False,
                       xanchor="left", yanchor="bottom", font=dict(size=11, color=MAMDANI))
    base_layout(fig, height=480, hovermode="x unified")
    fig.update_annotations(font=dict(size=13, color=INK))
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_equity_heatmap():
    y = qol_yearly[qol_yearly["year"].isin([2025, 2026]) & ~qol_yearly["borough"].isin(["CITYWIDE", "UNSPECIFIED"])]
    p = y.pivot_table(index="borough", columns=["problem", "year"], values="closed_7d")
    delta = pd.DataFrame({prob: (p[(prob, 2026)] - p[(prob, 2025)]) * 100 for prob in PROBLEMS})
    delta.index = delta.index.str.title()
    text = delta.map(lambda v: f"{v:+.0f}")
    fig = go.Figure(go.Heatmap(
        z=delta.values, x=delta.columns, y=delta.index, text=text.values, texttemplate="%{text}",
        textfont=dict(size=13), colorscale=DIVERGING, zmid=0, zmin=-50, zmax=50, xgap=2, ygap=2,
        colorbar=dict(title=dict(text="pts", side="top"), thickness=10, len=0.9, tickfont=dict(color=MUTED)),
        hovertemplate="%{y} · %{x}<br>%{z:+.1f} pts closed within 7 days (2026 vs 2025)<extra></extra>"))
    base_layout(fig, height=320)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(side="top", tickfont=dict(color=INK_2))
    fig.update_layout(margin=dict(l=110, r=24, t=48, b=16))
    return fig


# ======================================================================================
# Headline numbers (computed, not typed in)
# ======================================================================================

def kpis():
    cw = qol_yearly[qol_yearly["borough"] == "CITYWIDE"].set_index(["problem", "year"])["closed_7d"]
    hy = heat_yearly[heat_yearly["borough"] == "CITYWIDE"].set_index("year")
    pb = qol_monthly[(qol_monthly["borough"] == "CITYWIDE") & (qol_monthly["problem"] == "Potholes")].set_index("month")
    hm = homeless[homeless["borough"] == "CITYWIDE"].set_index("date")["complaints"]
    a = all_311[all_311["month"].dt.month <= 9]
    by = a.pivot_table(index=a["month"].dt.year, columns="channel", values="n", aggfunc="sum")
    return {
        "volume_growth": by.loc[2026].sum() / by.loc[2025].sum() - 1,
        "online_growth": by.loc[2026, "Online"] - by.loc[2025, "Online"],
        "phone_growth": by.loc[2026, "Phone"] - by.loc[2025, "Phone"],
        "cold_nights": int(winters.set_index("season").loc["2025-26", "days_below_20"]),
        "cold_nights_prev_max": int(winters[winters["season"] != "2025-26"]["days_below_20"].max()),
        "heat_7d_2025": hy.loc[2025, "closed_7d"], "heat_7d_2026": hy.loc[2026, "closed_7d"],
        "heat_open_2025": int(hy.loc[2025, "open_after_30d"]), "heat_open_2026": int(hy.loc[2026, "open_after_30d"]),
        "trash_2025": cw[("Missed trash collection", 2025)], "trash_2026": cw[("Missed trash collection", 2026)],
        "dump_2025": cw[("Illegal dumping", 2025)], "dump_2026": cw[("Illegal dumping", 2026)],
        "pothole_2025": cw[("Potholes", 2025)], "pothole_2026": cw[("Potholes", 2026)],
        "pothole_backlog_dec": int(pb.loc["2025-12-01", "open_backlog"]),
        "pothole_backlog_now": int(pb["open_backlog"].iloc[-1]),
        "homeless_peak": int(hm.loc["2026-01-24":"2026-01-30"].mean()),
        "homeless_reroute": hm.loc[REROUTE[0]:REROUTE[1]].mean(),
    }


K = kpis()


# ======================================================================================
# Layout
# ======================================================================================

def verdict(status, title, line):
    icon, color = {"good": ("✓", GOOD), "mixed": ("◐", WARN), "bad": ("✕", BAD)}[status]
    label = {"good": "Improving", "mixed": "Mixed", "bad": "Getting worse"}[status]
    return html.Div(className="verdict", children=[
        html.Div(className="verdict-head", children=[
            html.Span(icon, className="verdict-icon", style={"background": color}),
            html.Span(label, className="verdict-label")]),
        html.H3(title), html.P(line)])


def stat(value, label, sub=None):
    return html.Div(className="stat", children=[
        html.Div(value, className="stat-value"), html.Div(label, className="stat-label"),
        html.Div(sub, className="stat-sub") if sub else None])


def card(title, takeaway, graph, note=None):
    return html.Div(className="card", children=[
        html.H4(title), html.P(takeaway, className="takeaway"), graph,
        html.P(note, className="note") if note else None])


def graph(fig_or_id, fig=None):
    cfg = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    if isinstance(fig_or_id, str):
        return dcc.Graph(id=fig_or_id, config=cfg)
    return dcc.Graph(figure=fig_or_id, config=cfg)


app = Dash(__name__, title="Mamdani 311 Report Card")
server = app.server  # WSGI entry point for gunicorn / Plotly Cloud

app.layout = html.Div(className="page", children=[
    html.Header(className="hero", children=[
        html.P("NYC 311 · January 2022 – " + AS_OF, className="eyebrow"),
        html.H1("Is Mayor Mamdani doing a good job?"),
        html.P(["Ten months in, the 311 record says: ", html.Strong("trash pickup got clearly better, "),
                "the cold-weather emergency plan was carried out, but ",
                html.Strong("heat complaints and potholes are being closed more slowly than under Adams"),
                " – and the winter was the harshest in years. Every comparison below uses the same calendar "
                "window in each year, so seasonality isn't mistaken for performance."], className="lede"),
    ]),

    html.Section(className="verdicts", children=[
        verdict("mixed", "Extreme weather & life safety",
                f"The 311→911 cold-emergency reroute shows up clearly. But heat tickets closed within a week fell "
                f"from {pct(K['heat_7d_2025'])} to {pct(K['heat_7d_2026'])}, and that holds at every temperature."),
        verdict("good", "Trash & illegal dumping",
                f"Missed collections closed within a week: {pct(K['trash_2025'])} → {pct(K['trash_2026'])}. "
                f"Illegal dumping: {pct(K['dump_2025'])} → {pct(K['dump_2026'])}. The biggest gains were in the Bronx."),
        verdict("bad", "Potholes",
                f"A record freeze-thaw spring swamped crews: closed within a week fell from {pct(K['pothole_2025'])} to "
                f"{pct(K['pothole_2026'])}, and the open backlog has roughly doubled and isn't shrinking."),
    ]),

    html.Div(className="filters", children=[
        html.Label("Borough", htmlFor="borough"),
        dcc.Dropdown(id="borough", options=BOROUGH_OPTIONS, value="CITYWIDE", clearable=False, searchable=False),
        html.Span("Applies to every borough-level chart below.", className="filters-hint"),
    ]),

    # ---- context ----
    html.Section(children=[
        html.H2("First, a warning about counting 311 calls"),
        html.P("More 311 requests doesn't mean the city got worse – it can mean people trust 311 more, or that "
               "the city is promoting it. That's why this report judges the administration on how fast and how "
               "completely tickets get closed, not on how many come in.", className="section-lede"),
        card("Overall 311 volume and how people file",
             f"311 volume is up {K['volume_growth']:.0%} on 2025, and the growth came online (+{K['online_growth'] / 1000:,.0f}k "
             f"requests) while phone calls fell ({K['phone_growth'] / 1000:+,.0f}k). That looks like more New Yorkers "
             "using 311, not a city falling apart – so volume alone can't grade the mayor.",
             graph(fig_311_volume()),
             "Jan–Sep of each year. Requests from all problem types."),
    ]),

    # ---- question 1 ----
    html.Section(children=[
        html.H2("1 · Extreme weather & life safety"),
        html.P("Any fair grade has to start with the weather: January–February 2026 was the coldest stretch "
               "New York has seen in this period.", className="section-lede"),
        html.Div(className="grid-2", children=[
            card("The hardest winter in five years",
                 f"{K['cold_nights']} nights at or below 20°F – nearly double the previous high of "
                 f"{K['cold_nights_prev_max']}.", graph(fig_winters()),
                 "Central Park overnight lows, Nov–Mar. Source: Open-Meteo historical weather archive."),
            card("Complaints tracked the cold, not a publicity push",
                 "On days with the same overnight low, Mamdani-era days drew about the same number of heat complaints "
                 "as Adams-era days. The 2026 surge is the weather.", graph(fig_heat_scatter()),
                 "Each dot is one day, Nov–Mar, 2022–2026. Citywide."),
        ]),
        card("Heat & hot-water complaints, winter by winter",
             "The 2025–26 winter (blue) towers over earlier ones during the late-January deep freeze.",
             graph("heat-season"), "Lines show each winter aligned on the calendar. Lower panel: 2025–26 overnight lows."),
        html.Div(className="grid-2", children=[
            card("Slower to close heat tickets – at every temperature",
                 "If cold alone explained the slowdown, warm days would look like Adams-era days. They don't: the gap "
                 "is there on mild days too, which points at the system, not the weather.",
                 graph(fig_heat_bands()), "Citywide, Nov–Mar. Only tickets at least 7 days old are counted."),
            card("Heat tickets left hanging",
                 f"Citywide, tickets from Jan–Sep that took 30+ days or are still open: {K['heat_open_2025']:,} in 2025 vs. "
                 f"{K['heat_open_2026']:,} in 2026. The problem began creeping up in Adams' last year.",
                 graph("heat-open")),
        ]),
        card("The 311→911 reroute is visible in the data",
             f"During the late-January deep freeze homeless-assistance requests hit ~{K['homeless_peak']} a day. When the "
             f"Code Blue reroute began, they fell to about {K['homeless_reroute']:.0f} a day – those calls went to 911 "
             "instead. 311 data can confirm the policy was carried out, but it can't tell us whether it saved lives; "
             "news reports counted 16–17 outdoor deaths during the cold snap.",
             graph("homeless"), "Shaded: Jan 31 – Feb 12, 2026, when 311 homeless-assistance tickets nearly vanished."),
    ]),

    # ---- question 2 ----
    html.Section(children=[
        html.H2("2 · Quality of life & neighborhood repairs"),
        html.P("“No pothole too far, no trash pile too high.” Here the record splits cleanly in two.",
               className="section-lede"),
        card("Share of tickets closed within a week: 2025 vs. 2026",
             "Sanitation problems are getting fixed faster. Potholes and snow/ice – both hit hard by the winter – "
             "are slower.", graph("qol-dumbbell"),
             "Tickets opened Jan 1 – Aug 31 of each year, so both years cover the same months."),
        card("Who gained the most? Change by borough",
             "Blue = faster than 2025, red = slower. The Bronx, which had the worst trash response in 2025, "
             "improved the most. Pothole slowdowns hit every borough.", graph(fig_equity_heatmap()),
             "Percentage-point change in tickets closed within 7 days, Jan–Aug 2026 vs. Jan–Aug 2025."),
        html.Div(className="card", children=[
            html.H4("Is the backlog shrinking?"),
            html.P(f"Pick a problem. Pothole backlog: {K['pothole_backlog_dec']:,} open at the end of 2025, "
                   f"{K['pothole_backlog_now']:,} now – it jumped in March and hasn't come back down. "
                   "Missed-collection backlog, by contrast, sits near historic lows.", className="takeaway"),
            dcc.RadioItems(id="problem", options=PROBLEMS, value="Potholes", inline=True, className="radio"),
            graph("qol-trend"),
            html.P("Backlog = tickets opened by month end that hadn't been closed by month end.", className="note"),
        ]),
    ]),

    # ---- bottom line ----
    html.Section(className="bottom", children=[
        html.H2("The bottom line"),
        html.Div(className="stats", children=[
            stat(f"{pct(K['trash_2025'])} → {pct(K['trash_2026'])}", "missed trash closed within a week", "Clear improvement"),
            stat(f"{pct(K['heat_7d_2025'])} → {pct(K['heat_7d_2026'])}", "heat tickets closed within a week", "Worse, not explained by cold"),
            stat(f"{K['pothole_backlog_dec'] / 1000:.1f}k → {K['pothole_backlog_now'] / 1000:.1f}k", "open pothole tickets", "Backlog doubled"),
        ]),
        html.P("On the evidence in 311, Mamdani is doing a good job on sanitation, delivered the emergency steps he "
               "promised during the cold snap, and is falling short on heat enforcement and pothole repair – the two "
               "areas the record winter hit hardest. Ten months is a short track record, the heat slowdown started "
               "under Adams, and 311 closing times measure paperwork as well as real repairs. So the honest grade is "
               "a mixed one: promising where the administration has focused, and not yet proven where the weather "
               "fought back."),
        html.H4("What 311 can't tell you"),
        html.Ul([
            html.Li("Whether a closed ticket was actually fixed – agencies close tickets for many reasons, including "
                    "“no violation found” or a landlord restoring heat on their own."),
            html.Li("Outcomes such as cold-weather deaths, shelter placements, or warming-center use."),
            html.Li("2026 is a partial year; later tickets have had less time to close (so the report only counts "
                    "tickets old enough to have had the full 7 or 30 days)."),
        ]),
        html.P(["Data: NYC Open Data, ", html.A("311 Service Requests from 2020 to Present",
                href="https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9"),
                " (problem types HEAT/HOT WATER, Street Condition › Pothole, Illegal Dumping, Missed Collection, "
                "Dirty Condition, Snow or Ice, Homeless Person Assistance). Weather: ",
                html.A("Open-Meteo", href="https://open-meteo.com/"), ". Starts in 2022 because 311 renamed its "
                "sanitation problem types in late 2021."], className="note"),
    ]),
])


@app.callback(
    Output("heat-season", "figure"), Output("heat-open", "figure"), Output("homeless", "figure"),
    Output("qol-dumbbell", "figure"), Input("borough", "value"))
def update_borough(borough):
    return fig_heat_season(borough), fig_heat_open(borough), fig_homeless(borough), fig_qol_dumbbell(borough)


@app.callback(Output("qol-trend", "figure"), Input("borough", "value"), Input("problem", "value"))
def update_trend(borough, problem):
    return fig_qol_trend(borough, problem)


if __name__ == "__main__":
    app.run(debug=True)
