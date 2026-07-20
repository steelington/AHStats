"""Parsers turning the raw HTML from each stats endpoint into plain
dataclasses / dicts. All four pages are old-school table-based HTML with
no ids or classes to hook into, so parsing is done by matching header
text rather than CSS selectors.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger('ahstats.parser')


def _text(el) -> str:
    return el.get_text(strip=True).replace("\xa0", " ").strip() if el else ""


def _to_int(s: str, default=0):
    s = s.strip().replace(",", "")
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else default


def _to_float(s: str, default=0.0):
    s = s.strip().replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else default


def _to_seconds(hms: str) -> int:
    """Parse 'hh:mm:ss' (optionally with a leading 'N days ' prefix) into
    total seconds."""
    hms = hms.strip()
    days = 0
    day_match = re.match(r"(\d+)\s*day", hms)
    if day_match:
        days = int(day_match.group(1))
        hms = hms.split("day", 1)[1].lstrip("s ").strip()
    parts = hms.split(":")
    if len(parts) != 3:
        return days * 86400
    h, m, s = (int(p) for p in parts)
    return days * 86400 + h * 3600 + m * 60 + s


# ---------------------------------------------------------------------------
# ahscore/index.php - pilot or squad score summary for one tour
# ---------------------------------------------------------------------------

@dataclass
class TourOption:
    tourid: str
    label: str
    start_date: str
    end_date: str


@dataclass
class PilotTourScores:
    pilot_name: str
    tour_label: str
    tours: list = field(default_factory=list)  # list[TourOption]
    # scores[category][metric] = {"score": float, "rank": int|None}
    scores: dict = field(default_factory=dict)
    # totals[category][field] = int  (fields: kills, assists, sorties,
    # landed, bailed, ditched, captured, deaths, discos, time_seconds, rank)
    totals: dict = field(default_factory=dict)


_TOUR_OPTION_RE = re.compile(
    r"^(?P<label>.+?)\s+(?P<start>\d{4}-\d{2}-\d{2})\s+to\s+(?P<end>\d{4}-\d{2}-\d{2})$"
)

_CATEGORY_ALIAS = {
    "vehicles and boats": "vehicle",
    "veh/boat": "vehicle",
    "veh./boat": "vehicle",
}

_TOTALS_FIELD_MAP = {
    "kills": "kills",
    "assists": "assists",
    "sorties": "sorties",
    "landed": "landed",
    "bailed": "bailed",
    "ditched": "ditched",
    "captured": "captured",
    "deaths": "deaths",
    "discos": "discos",
    "time hh:mm:ss": "time_seconds",
    "rank": "rank",
}


def parse_tour_list(soup: BeautifulSoup) -> list:
    """Extract the tour dropdown (<select name="tourid">) - present on
    every ahscore page regardless of whether a pilot lookup succeeded."""
    tours = []
    select = soup.find("select", attrs={"name": "tourid"})
    if select:
        for opt in select.find_all("option"):
            tourid = opt.get("value", "")
            raw = _text(opt)
            m = _TOUR_OPTION_RE.match(raw)
            if m:
                tours.append(
                    TourOption(tourid=tourid, label=m.group("label"), start_date=m.group("start"), end_date=m.group("end"))
                )
    return tours


def parse_pilot_tour_scores(html: str) -> PilotTourScores | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")

    header = soup.find("h2", string=re.compile(r"^Scores for .+ in .+|^Player .+ did not fly"))
    if header is None:
        return None
    header_text = header.get_text(strip=True)
    m = re.match(r"^Scores for (.+) in (.+)$", header_text)
    if m:
        pilot_name, tour_label = m.group(1), m.group(2)
    else:
        # "Player X did not fly in <tour>" - valid response, just no
        # activity that tour. Caller should still cache this as "checked".
        m = re.match(r"^Player (.+?) did not fly in\s*(.*)$", header_text)
        pilot_name, tour_label = (m.group(1), m.group(2)) if m else ("", "")

    result = PilotTourScores(pilot_name=pilot_name, tour_label=tour_label)
    result.tours = parse_tour_list(soup)

    for table in soup.find_all("table", class_="user1_inner"):
        rows = table.find_all("tr")
        if not rows:
            continue
        title = _text(rows[0].find("td"))

        if title.endswith("Scores"):
            category = title[: -len(" Scores")].strip().lower()
            category = _CATEGORY_ALIAS.get(category, category)
            metrics = {}
            for row in rows[2:]:  # skip title row + column-header row
                cells = row.find_all("td")
                if len(cells) != 3:
                    continue
                metric_name = _text(cells[0])
                if not metric_name:
                    continue
                metrics[metric_name] = {
                    "score": _to_float(_text(cells[1])),
                    "rank": _to_int(_text(cells[2])) if _text(cells[2]) else None,
                }
            if metrics:
                result.scores[category] = metrics

        elif title == "Statistics":
            header_cells = rows[1].find_all("td")
            categories = [_text(c).lower().rstrip(".") for c in header_cells[1:]]
            categories = [_CATEGORY_ALIAS.get(c, c) for c in categories]
            for cat in categories:
                result.totals.setdefault(cat, {})
            for row in rows[2:]:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                label = _text(cells[0]).lower()
                field_name = _TOTALS_FIELD_MAP.get(label)
                if not field_name:
                    continue
                for cat, cell in zip(categories, cells[1:]):
                    raw_val = _text(cell)
                    if field_name == "time_seconds":
                        result.totals[cat][field_name] = _to_seconds(raw_val)
                    elif field_name == "rank":
                        result.totals[cat][field_name] = _to_int(raw_val) if raw_val else None
                    else:
                        result.totals[cat][field_name] = _to_int(raw_val)

    return result


# ---------------------------------------------------------------------------
# scores/squadstats.php - roster + stats for a player's current squad
# ---------------------------------------------------------------------------

@dataclass
class SquadMember:
    name: str
    kills: int
    kill_pct: float
    deaths: int
    death_pct: float
    kd_ratio: float
    active: bool  # inactive members are shown in <i>italics</i> with no link


@dataclass
class SquadStats:
    squad_name: str
    squad_co: str
    member_count: int
    tour_label: str
    members: list = field(default_factory=list)  # list[SquadMember]
    general_stats: dict = field(default_factory=dict)


def parse_squad_stats(html: str) -> SquadStats | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", class_="user1_inner")

    roster_table = None
    for t in tables:
        if t.find("td", string=re.compile(r"^Player.?Name$")):
            roster_table = t
            break
    if roster_table is None:
        return None

    rows = roster_table.find_all("tr")
    squad_name = ""
    squad_co = ""
    member_count = 0
    header_idx = 0
    for i, row in enumerate(rows):
        txt = re.sub(r"&nbsp;?", "", _text(row.find("td"))).strip()
        if not txt:
            continue
        if txt == "Player Name":
            header_idx = i
            break
        if txt.startswith("Squad CO:"):
            squad_co = txt.split(":", 1)[1].strip()
        elif txt.startswith("Number of Members:"):
            member_count = _to_int(txt)
        elif not squad_name:
            squad_name = txt

    # Columns are: Player Name, Kills, %, Deaths, %, K/D Ratio (6 cells per row)
    members = []
    for row in rows[header_idx + 1 :]:
        cells = row.find_all("td")
        if len(cells) != 6:
            continue
        name_cell = cells[0]
        link = name_cell.find("a")
        members.append(
            SquadMember(
                name=_text(name_cell),
                kills=_to_int(_text(cells[1])),
                kill_pct=_to_float(_text(cells[2])),
                deaths=_to_int(_text(cells[3])),
                death_pct=_to_float(_text(cells[4])),
                kd_ratio=_to_float(_text(cells[5])),
                active=link is not None,
            )
        )

    tour_label = ""
    general_stats = {}
    for t in tables:
        first_td = t.find("td")
        if first_td and "General Stats" in _text(first_td):
            txt = _text(first_td)
            m = re.search(r"for (.+?)Total Sorties: (\d+)Total Sortie Time:\s*(.+)$", txt)
            if m:
                tour_label = m.group(1)
                general_stats["total_sorties"] = _to_int(m.group(2))
                general_stats["total_sortie_time_seconds"] = _to_seconds(m.group(3))
            for row in t.find_all("tr")[2:]:
                cells = row.find_all("td")
                if len(cells) == 5:
                    left_label, left_val = _text(cells[0]), _text(cells[1])
                    right_label, right_val = _text(cells[3]), _text(cells[4])
                    if left_label:
                        general_stats[left_label.lower()] = _to_int(left_val)
                    if right_label:
                        general_stats[right_label.lower()] = _to_int(right_val)
            break

    return SquadStats(
        squad_name=squad_name,
        squad_co=squad_co,
        member_count=member_count,
        tour_label=tour_label,
        members=members,
        general_stats=general_stats,
    )


# ---------------------------------------------------------------------------
# scores/planes.php - arena-wide kills/deaths leaderboard by plane type
# ---------------------------------------------------------------------------

@dataclass
class PlaneLeaderboardEntry:
    plane: str
    pindex: int | None
    kills: int
    deaths: int
    kd_ratio: float


@dataclass
class PlaneLeaderboard:
    tour_label: str
    planes: list = field(default_factory=list)  # list[PlaneLeaderboardEntry]
    total_kills: int = 0
    total_deaths: int = 0


_PINDEX_RE = re.compile(r"pindex=(\d+)")


def parse_plane_leaderboard(html: str) -> PlaneLeaderboard | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table", class_="user1_inner"):
        if t.find("td", string=re.compile(r"Statistics for all planes")):
            table = t
            break
    if table is None:
        return None

    rows = table.find_all("tr")
    tour_label = _text(rows[0].find("td"))
    tour_label = tour_label.replace(" Statistics for all planes/vehicles/boats", "")

    result = PlaneLeaderboard(tour_label=tour_label)
    for row in rows[2:]:
        cells = row.find_all("td")
        if len(cells) != 4:
            continue
        name_cell = cells[0]
        if "Totals" in _text(name_cell):
            result.total_kills = _to_int(_text(cells[1]))
            result.total_deaths = _to_int(_text(cells[2]))
            continue
        link = name_cell.find("a")
        pindex = None
        if link and link.get("href"):
            m = _PINDEX_RE.search(link["href"])
            pindex = int(m.group(1)) if m else None
        result.planes.append(
            PlaneLeaderboardEntry(
                plane=_text(name_cell),
                pindex=pindex,
                kills=_to_int(_text(cells[1])),
                deaths=_to_int(_text(cells[2])),
                kd_ratio=_to_float(_text(cells[3])),
            )
        )
    return result


# ---------------------------------------------------------------------------
# newscores/killstat.php - one pilot's kills broken down by plane type
# ---------------------------------------------------------------------------

@dataclass
class PilotPlaneKillEntry:
    plane: str
    days_1_7: int
    days_8_14: int
    days_15_21: int
    days_22_28: int
    days_28_up: int
    total: int


@dataclass
class PilotPlaneKills:
    pilot_name: str
    tour_label: str
    planes: list = field(default_factory=list)  # list[PilotPlaneKillEntry]
    total_kills: int = 0
    total_kills_toward_rank: int = 0
    total_kills_not_toward_rank: int = 0


def parse_pilot_plane_kills(html: str) -> PilotPlaneKills | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="user1_inner")
    if table is None:
        return None

    rows = table.find_all("tr")
    header_txt = _text(rows[0].find("td"))
    m = re.match(r"^(.+) Kill Stats for (.+)$", header_txt)
    pilot_name, tour_label = (m.group(1), m.group(2)) if m else ("", "")

    result = PilotPlaneKills(pilot_name=pilot_name, tour_label=tour_label)
    for row in rows[2:]:
        cells = row.find_all("td")
        if len(cells) == 7:
            plane = _text(cells[0])
            if plane == "Total Kills":
                result.total_kills = _to_int(_text(cells[1]))
                continue
            result.planes.append(
                PilotPlaneKillEntry(
                    plane=plane,
                    days_1_7=_to_int(_text(cells[1])),
                    days_8_14=_to_int(_text(cells[2])),
                    days_15_21=_to_int(_text(cells[3])),
                    days_22_28=_to_int(_text(cells[4])),
                    days_28_up=_to_int(_text(cells[5])),
                    total=_to_int(_text(cells[6])),
                )
            )
        elif len(cells) == 2:
            label = _text(cells[0])
            if "towards Rank" in label and "not" not in label:
                result.total_kills_toward_rank = _to_int(_text(cells[1]))
            elif "not counted towards Rank" in label:
                result.total_kills_not_toward_rank = _to_int(_text(cells[1]))

    return result


# ---------------------------------------------------------------------------
# scores/players.php - one pilot's full per-plane kill matrix (kills in/of,
# killed by, died in) plus a sortie-type breakdown including Field Gunner.
# ---------------------------------------------------------------------------

@dataclass
class PilotPlaneMatrixEntry:
    plane: str
    kills_in: int   # kills scored while flying this plane
    kills_of: int    # kills scored against this enemy plane type
    killed_by: int   # times killed by this enemy plane type
    died_in: int      # times died while flying this plane


@dataclass
class PlayerPlaneStats:
    pilot_name: str
    tour_label: str
    general_stats: dict = field(default_factory=dict)
    planes: list = field(default_factory=list)  # list[PilotPlaneMatrixEntry]
    total_kills: int = 0
    total_deaths: int = 0


def parse_player_plane_stats(html: str) -> PlayerPlaneStats | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", class_="user1_inner")

    pilot_name = ""
    tour_label = ""
    general_stats = {}
    for t in tables:
        first_td = t.find("td")
        if first_td and "General Stats" in _text(first_td):
            txt = _text(first_td)
            m = re.match(r"^(.+?)'s General Stats for (.+?)Total Sorties: (\d+)Total Sortie Time:\s*(.+)$", txt)
            if m:
                pilot_name = m.group(1)
                tour_label = m.group(2)
                general_stats["total_sorties"] = _to_int(m.group(3))
                general_stats["total_sortie_time_seconds"] = _to_seconds(m.group(4))
            for row in t.find_all("tr")[2:]:
                cells = row.find_all("td")
                if len(cells) == 5:
                    left_label, left_val = _text(cells[0]), _text(cells[1])
                    right_label, right_val = _text(cells[3]), _text(cells[4])
                    if left_label:
                        general_stats[left_label.lower().replace(" ", "").replace("/", "")] = _to_int(left_val)
                    if right_label:
                        general_stats[right_label.lower().replace(" ", "")] = _to_int(right_val)
            break

    result = PlayerPlaneStats(pilot_name=pilot_name, tour_label=tour_label, general_stats=general_stats)

    matrix_table = None
    for t in tables:
        if t.find("td", string=re.compile(r"Model.?Type")):
            matrix_table = t
            break
    if matrix_table is None:
        return result if pilot_name else None

    rows = matrix_table.find_all("tr")
    for row in rows[2:]:
        cells = row.find_all("td")
        if len(cells) == 5:
            plane = _text(cells[0])
            if not plane:
                continue
            result.planes.append(
                PilotPlaneMatrixEntry(
                    plane=plane,
                    kills_in=_to_int(_text(cells[1])),
                    kills_of=_to_int(_text(cells[2])),
                    killed_by=_to_int(_text(cells[3])),
                    died_in=_to_int(_text(cells[4])),
                )
            )
        elif len(cells) == 3:
            # Footer row: '', 'N Kills', 'N Deaths'
            result.total_kills = _to_int(_text(cells[1]))
            result.total_deaths = _to_int(_text(cells[2]))

    return result
