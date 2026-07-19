"""CSV and standalone-HTML export of cached pilot stats."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from ahstats.db import StatsDB


def _seconds_to_hms(total: int | None) -> str:
    if not total:
        return "00:00:00"
    h, rem = divmod(int(total), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def export_pilot_tours_csv(db: StatsDB, gameid: str, stype: str, path: str | Path) -> None:
    """One row per cached tour, 'total' category numbers."""
    tours = {t["tourid"]: t for t in db.get_tours()}
    fieldnames = [
        "tour", "start_date", "end_date", "arena", "kills", "assists", "sorties",
        "landed", "bailed", "ditched", "captured", "deaths", "discos", "time_hms", "rank",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for tourid in db.get_pilot_tourids(gameid, stype):
            rows = {r["category"]: r for r in db.get_pilot_totals(gameid, stype, tourid)}
            total = rows.get("total")
            if not total:
                continue
            tour = tours.get(tourid)
            writer.writerow({
                "tour": tour["label"] if tour else tourid,
                "start_date": tour["start_date"] if tour else "",
                "end_date": tour["end_date"] if tour else "",
                "arena": tour["arena"] if tour else "",
                "kills": total["kills"], "assists": total["assists"], "sorties": total["sorties"],
                "landed": total["landed"], "bailed": total["bailed"], "ditched": total["ditched"],
                "captured": total["captured"], "deaths": total["deaths"], "discos": total["discos"],
                "time_hms": _seconds_to_hms(total["time_seconds"]), "rank": total["rank"],
            })


def export_pilot_plane_kills_csv(db: StatsDB, gameid: str, path: str | Path) -> None:
    """Career kills-by-plane-type, summed across every cached tour."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["plane", "career_kills"])
        for row in db.get_career_kills_by_plane(gameid):
            writer.writerow([row["plane"], row["kills"]])


def _prepare_chart_data(tours: dict, per_tour: dict, career: dict) -> dict:
    """Compute time-series and distribution data for charts."""
    # Sort tours chronologically
    sorted_tours = sorted(
        [(tid, data) for tid, data in per_tour.items()],
        key=lambda x: tours.get(x[0], {}).get("start_date", ""),
    )

    # Kill progression over time
    kill_trend = []
    for tid, data in sorted_tours:
        total = data["categories"].get("total", {})
        tour_info = tours.get(tid)
        if tour_info and total:
            kills = total.get("kills", 0)
            deaths = total.get("deaths", 0)
            kill_trend.append({
                "label": tour_info.get("label", tid),
                "date": tour_info.get("start_date", ""),
                "kills": kills,
                "deaths": deaths,
                "sorties": total.get("sorties", 0),
                "kd": round(kills / deaths, 2) if deaths else kills,
            })

    # Category breakdown (aggregate across all tours)
    category_totals = {"fighter": 0, "bomber": 0, "attack": 0, "vehicle": 0}
    for _, data in per_tour.items():
        for cat in category_totals.keys():
            category_totals[cat] += data["categories"].get(cat, {}).get("kills", 0)

    return {
        "killTrend": kill_trend,
        "categoryBreakdown": [
            {"category": cat.title(), "kills": kills}
            for cat, kills in category_totals.items() if kills > 0
        ],
    }


def export_html_report(db: StatsDB, gameid: str, stype: str, path: str | Path) -> None:
    """Self-contained HTML report: career summary + kills-by-plane, and a
    tour picker that switches between cached tours client-side (no
    network calls, no external assets - everything is embedded)."""
    tours = {t["tourid"]: t for t in db.get_tours()}
    tourids = sorted(
        db.get_pilot_tourids(gameid, stype),
        key=lambda tid: (tours[tid]["start_date"] if tid in tours else ""),
        reverse=True,
    )

    per_tour = {}
    for tourid in tourids:
        rows = {r["category"]: dict(r) for r in db.get_pilot_totals(gameid, stype, tourid)}
        tour = tours.get(tourid)
        per_tour[tourid] = {
            "label": tour["label"] if tour else tourid,
            "arena": tour["arena"] if tour else "",
            "categories": rows,
        }

    career = dict(db.get_career_totals(gameid, stype))
    kills_by_plane = [dict(r) for r in db.get_career_kills_by_plane(gameid)]

    # Prepare chart datasets
    chart_data = _prepare_chart_data(tours, per_tour, career)

    data_json = json.dumps({
        "per_tour": per_tour,
        "career": career,
        "kills_by_plane": kills_by_plane,
        "charts": chart_data,
    })
    safe_gameid = html.escape(gameid)

    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Aces High Stats - {gameid}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"></script>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; background: #0f1419; color: #d8dee9; margin: 0; padding: 24px; }}
  h1 {{ margin-top: 0; color: #eceff4; }}
  h2 {{ border-bottom: 2px solid #4a5a42; padding-bottom: 4px; color: #eceff4; }}
  select {{ font-size: 15px; padding: 4px 8px; margin-bottom: 16px; background: #1a1f26; color: #d8dee9; border: 1px solid #2e3440; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
  th, td {{ padding: 6px 10px; text-align: right; border-bottom: 1px solid #2e3440; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #1a1f26; color: #e5e9f0; }}
  tr:nth-child(even) {{ background: #1a1f26; }}
  .muted {{ color: #999; font-size: 13px; }}
  .chart-container {{ max-width: 900px; margin: 20px auto; padding: 20px; background: #1a1f26; border-radius: 6px; }}
  .chart-container.small {{ max-width: 600px; }}
</style>
</head>
<body>
<h1>Aces High Stats &mdash; {gameid}</h1>

<h2>Career Totals</h2>
<div id="career"></div>

<h2>Career Progression</h2>
<div class="chart-container">
  <canvas id="killTrendChart"></canvas>
</div>

<h2>Kill Distribution</h2>
<div class="chart-container small">
  <canvas id="categoryChart"></canvas>
</div>

<h2>Career Kills by Plane</h2>
<div id="planes"></div>

<h2>Tour Detail</h2>
<select id="tourSelect"></select>
<div id="tourDetail"></div>

<script>
const DATA = {data_json};

function fmtTime(sec) {{
  if (!sec) return "00:00:00";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return String(h).padStart(2,'0') + ":" + String(m).padStart(2,'0') + ":" + String(s).padStart(2,'0');
}}

function renderCareer() {{
  const c = DATA.career;
  const el = document.getElementById("career");
  el.innerHTML = `<table><tr>
    <th>Tours</th><th>Kills</th><th>Assists</th><th>Sorties</th><th>Deaths</th>
    <th>K/D</th><th>Flight Time</th></tr><tr>
    <td>${{c.tours || 0}}</td><td>${{c.kills || 0}}</td><td>${{c.assists || 0}}</td>
    <td>${{c.sorties || 0}}</td><td>${{c.deaths || 0}}</td>
    <td>${{c.deaths ? (c.kills / c.deaths).toFixed(2) : c.kills}}</td>
    <td>${{fmtTime(c.time_seconds)}}</td></tr></table>`;
}}

function renderPlanes() {{
  const rows = DATA.kills_by_plane.map(p => `<tr><td>${{p.plane}}</td><td>${{p.kills}}</td></tr>`).join("");
  document.getElementById("planes").innerHTML =
    `<table><tr><th>Plane</th><th>Kills</th></tr>${{rows}}</table>`;
}}

function renderTour(tourid) {{
  const t = DATA.per_tour[tourid];
  if (!t) {{ document.getElementById("tourDetail").innerHTML = ""; return; }}
  const cats = ["fighter", "bomber", "attack", "vehicle", "total"];
  const rows = cats.filter(c => t.categories[c]).map(c => {{
    const s = t.categories[c];
    return `<tr><td>${{c}}</td><td>${{s.kills}}</td><td>${{s.assists}}</td><td>${{s.sorties}}</td>
      <td>${{s.deaths}}</td><td>${{fmtTime(s.time_seconds)}}</td><td>${{s.rank ?? '-'}}</td></tr>`;
  }}).join("");
  document.getElementById("tourDetail").innerHTML =
    `<p class="muted">${{t.label}} (${{t.arena}})</p>
     <table><tr><th>Category</th><th>Kills</th><th>Assists</th><th>Sorties</th>
     <th>Deaths</th><th>Flight Time</th><th>Rank</th></tr>${{rows}}</table>`;
}}

const select = document.getElementById("tourSelect");
Object.keys(DATA.per_tour).forEach(tourid => {{
  const opt = document.createElement("option");
  opt.value = tourid;
  opt.textContent = DATA.per_tour[tourid].label;
  select.appendChild(opt);
}});
select.addEventListener("change", () => renderTour(select.value));

renderCareer();
renderPlanes();
if (select.options.length) renderTour(select.options[0].value);

// Chart rendering with Chart.js
function renderCharts() {{
  const charts = DATA.charts;

  // 1. Kill Progression Chart (Line chart with dual y-axis)
  const killCtx = document.getElementById("killTrendChart");
  if (killCtx && charts.killTrend.length > 0) {{
    new Chart(killCtx, {{
      type: "line",
      data: {{
        labels: charts.killTrend.map(d => d.label),
        datasets: [{{
          label: "Kills",
          data: charts.killTrend.map(d => d.kills),
          borderColor: "#4a5a42",
          backgroundColor: "rgba(74, 90, 66, 0.1)",
          tension: 0.3,
          fill: true,
          yAxisID: 'y'
        }}, {{
          label: "K/D Ratio",
          data: charts.killTrend.map(d => d.kd),
          borderColor: "#8b7355",
          backgroundColor: "rgba(139, 115, 85, 0.1)",
          tension: 0.3,
          yAxisID: 'y1'
        }}]
      }},
      options: {{
        responsive: true,
        interaction: {{
          mode: 'index',
          intersect: false
        }},
        plugins: {{
          title: {{
            display: true,
            text: "Kill Progression Over Tours",
            color: "#eceff4",
            font: {{ size: 16 }}
          }},
          legend: {{
            labels: {{ color: "#d8dee9" }}
          }}
        }},
        scales: {{
          y: {{
            type: 'linear',
            display: true,
            position: 'left',
            beginAtZero: true,
            ticks: {{ color: "#d8dee9" }},
            grid: {{ color: "#2e3440" }}
          }},
          y1: {{
            type: 'linear',
            display: true,
            position: 'right',
            beginAtZero: true,
            ticks: {{ color: "#d8dee9" }},
            grid: {{ drawOnChartArea: false }}
          }},
          x: {{
            ticks: {{
              color: "#d8dee9",
              maxRotation: 45,
              minRotation: 45
            }},
            grid: {{ color: "#2e3440" }}
          }}
        }}
      }}
    }});
  }}

  // 2. Category Breakdown Pie Chart
  const catCtx = document.getElementById("categoryChart");
  if (catCtx && charts.categoryBreakdown.length > 0) {{
    new Chart(catCtx, {{
      type: "pie",
      data: {{
        labels: charts.categoryBreakdown.map(d => d.category),
        datasets: [{{
          data: charts.categoryBreakdown.map(d => d.kills),
          backgroundColor: [
            "rgba(74, 90, 66, 0.9)",    // Fighter - olive
            "rgba(139, 115, 85, 0.9)",  // Bomber - tan
            "rgba(59, 130, 246, 0.9)",  // Attack - blue
            "rgba(139, 92, 246, 0.9)"   // Vehicle - purple
          ],
          borderColor: "#0f1419",
          borderWidth: 2
        }}]
      }},
      options: {{
        responsive: true,
        plugins: {{
          title: {{
            display: true,
            text: "Kills by Category",
            color: "#eceff4",
            font: {{ size: 16 }}
          }},
          legend: {{
            labels: {{ color: "#d8dee9" }},
            position: 'bottom'
          }}
        }}
      }}
    }});
  }}
}}

// Render charts after page loads
if (typeof Chart !== 'undefined') {{
  renderCharts();
}}
</script>
</body>
</html>
""".format(gameid=safe_gameid, data_json=data_json)

    Path(path).write_text(page, encoding="utf-8")
