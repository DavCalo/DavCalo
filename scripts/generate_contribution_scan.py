#!/usr/bin/env python3
"""Generate an animated GitHub contribution telemetry pass as accessible SVG.

The latest 26 contribution weeks are rendered as a compact telemetry matrix.
A small CubeSat performs a short pass over the data, briefly amplifying active
signals before coming to rest near a static ground station. The animation has a
long quiet interval, light and dark variants, and a reduced-motion fallback.

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from pathlib import Path

GRAPHQL_URL = "https://api.github.com/graphql"
QUERY = r"""
query ContributionCalendar($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
          }
        }
      }
    }
  }
}
"""

WIDTH = 920
HEIGHT = 236
GRID_X0 = 68.0
GRID_X1 = 724.0
GRID_Y0 = 114.0
GRID_ROW_GAP = 13.5
RECENT_WEEK_LIMIT = 26

ORBIT_Y = 54.0
SATELLITE_SCALE = 0.78
SCAN_DURATION = 30.0
TRAVEL_START = GRID_X0
TRAVEL_END = GRID_X1
FALLBACK_X = GRID_X1

CLIP_TOP = 102.0
CLIP_BOTTOM = 207.0
FLARE_MAIN_X = -25.0
FLARE_MAIN_WIDTH = 50.0
FLARE_CORE_X = -5.0
FLARE_CORE_WIDTH = 10.0

STATION_X = 840.0
STATION_Y = 184.0


@dataclass(frozen=True)
class Day:
    date: str
    weekday: int
    count: int


@dataclass(frozen=True)
class Calendar:
    contributions: int
    weeks: list[list[Day]]
    demo: bool = False


@dataclass(frozen=True)
class Geometry:
    week_count: int
    x0: float = GRID_X0
    x1: float = GRID_X1
    y0: float = GRID_Y0
    row_gap: float = GRID_ROW_GAP


PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "zero": "#C7D0DB",
        "levels": ["#7BA7BA", "#3188A8", "#16709A", "#4F46E5"],
        "flare": ["#63A7BD", "#2BA6C8", "#3B91C3", "#6D73EF"],
        "core_mid": "#E2F5FA",
        "core_high": "#EEF2FF",
        "track": "#94A3B8",
        "lane": "#CBD5E1",
        "scan": "#1683AD",
        "beam": "#38BDF8",
        "body": "#F8FAFC",
        "body_edge": "#334155",
        "solar": "#237FA5",
        "solar_edge": "#D7F0F8",
        "solar_line": "#BAE6FD",
        "core": "#4F46E5",
        "detail": "#64748B",
        "station": "#475569",
        "station_fill": "#E2E8F0",
        "pulse": "#0EA5E9",
    },
    "dark": {
        "zero": "#3B485B",
        "levels": ["#3D7D92", "#2B9BBE", "#65B8D2", "#A5B4FC"],
        "flare": ["#5DA8BC", "#64C7DF", "#7DD3FC", "#C7D2FE"],
        "core_mid": "#DCF7FC",
        "core_high": "#EEF2FF",
        "track": "#64748B",
        "lane": "#334155",
        "scan": "#7DD3FC",
        "beam": "#38BDF8",
        "body": "#E2E8F0",
        "body_edge": "#94A3B8",
        "solar": "#2F9CC2",
        "solar_edge": "#BAE6FD",
        "solar_line": "#BAE6FD",
        "core": "#A5B4FC",
        "detail": "#94A3B8",
        "station": "#94A3B8",
        "station_fill": "#334155",
        "pulse": "#7DD3FC",
    },
}


def fetch_calendar(login: str, token: str) -> Calendar:
    payload = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "contribution-telemetry-generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub GraphQL API: {exc.reason}") from exc

    if body.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {body['errors']}")
    user = body.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{login}' was not found")

    raw = user["contributionsCollection"]["contributionCalendar"]
    weeks = [
        [
            Day(
                date=item["date"],
                weekday=int(item["weekday"]),
                count=int(item["contributionCount"]),
            )
            for item in raw_week["contributionDays"]
        ]
        for raw_week in raw["weeks"]
    ]
    return Calendar(contributions=int(raw["totalContributions"]), weeks=weeks)


def demo_calendar(reference_date: date | None = None) -> Calendar:
    """Return deterministic sample data suitable for local previews."""
    rng = random.Random(20260723)
    end = reference_date or date.today()
    start = end - timedelta(days=365)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    day_count = (end - start).days + 1

    counts: list[int] = []
    for index in range(day_count):
        phase = 0.16 + 0.06 * (1 + math.sin(index / 23.0))
        burst = 0.14 if 0.48 * day_count < index < 0.70 * day_count else 0.0
        if rng.random() >= phase + burst:
            counts.append(0)
            continue
        amount = 1 + int(rng.expovariate(0.45))
        if rng.random() < 0.08:
            amount += rng.randint(5, 15)
        counts.append(min(amount, 28))

    weeks: list[list[Day]] = []
    for index, count in enumerate(counts):
        current = start + timedelta(days=index)
        weekday = (current.weekday() + 1) % 7
        if weekday == 0 or not weeks:
            weeks.append([])
        weeks[-1].append(Day(current.isoformat(), weekday, count))
    return Calendar(contributions=sum(counts), weeks=weeks, demo=True)


def recent_calendar(calendar: Calendar, week_limit: int = RECENT_WEEK_LIMIT) -> Calendar:
    if week_limit <= 0:
        raise ValueError("week_limit must be positive")
    selected = [list(week) for week in calendar.weeks[-week_limit:]]
    count = sum(day.count for week in selected for day in week)
    return Calendar(contributions=count, weeks=selected, demo=calendar.demo)


def flatten_days(calendar: Calendar) -> list[Day]:
    return [day for week in calendar.weeks for day in week]


def level_for(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = math.log1p(count) / math.log1p(max_count)
    return min(4, max(1, math.ceil(ratio * 4)))


def build_geometry(calendar: Calendar) -> Geometry:
    return Geometry(week_count=max(1, len(calendar.weeks)))


def x_for_week(week_index: int, geometry: Geometry) -> float:
    if geometry.week_count <= 1:
        return (geometry.x0 + geometry.x1) / 2
    return geometry.x0 + week_index * (
        (geometry.x1 - geometry.x0) / (geometry.week_count - 1)
    )


def y_for_weekday(weekday: int, geometry: Geometry) -> float:
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday must be between 0 and 6, got {weekday}")
    return geometry.y0 + weekday * geometry.row_gap


def circle_subpath(x: float, y: float, radius: float) -> str:
    return (
        f"M{x - radius:.2f},{y:.2f}"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {2 * radius:.2f},0"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {-2 * radius:.2f},0Z"
    )


def diamond_subpath(x: float, y: float, radius: float) -> str:
    return (
        f"M{x:.2f},{y - radius:.2f}"
        f"L{x + radius:.2f},{y:.2f}"
        f"L{x:.2f},{y + radius:.2f}"
        f"L{x - radius:.2f},{y:.2f}Z"
    )


def build_signal_paths(
    calendar: Calendar,
    geometry: Geometry,
) -> tuple[dict[int, str], dict[int, str], dict[str, str]]:
    max_count = max((day.count for day in flatten_days(calendar)), default=0)
    base_radii = [1.55, 2.05, 2.55, 3.10, 3.65]
    flare_radii = {1: 2.80, 2: 3.75}
    diamond_radii = {3: 5.50, 4: 7.00}

    base_parts: dict[int, list[str]] = {level: [] for level in range(5)}
    flare_parts: dict[int, list[str]] = {level: [] for level in range(1, 5)}
    core_parts: dict[str, list[str]] = {"mid": [], "high": []}

    for week_index, week in enumerate(calendar.weeks):
        x = x_for_week(week_index, geometry)
        for day in week:
            y = y_for_weekday(day.weekday, geometry)
            level = level_for(day.count, max_count)
            base_parts[level].append(circle_subpath(x, y, base_radii[level]))

            if level in (1, 2):
                flare_parts[level].append(circle_subpath(x, y, flare_radii[level]))
            elif level in (3, 4):
                flare_parts[level].append(diamond_subpath(x, y, diamond_radii[level]))

            if level in (2, 3):
                core_parts["mid"].append(circle_subpath(x, y, 1.25))
            elif level == 4:
                core_parts["high"].append(circle_subpath(x, y, 1.75))
                core_parts["high"].append(diamond_subpath(x, y, 2.85))

    base = {level: "".join(parts) for level, parts in base_parts.items() if parts}
    flare = {level: "".join(parts) for level, parts in flare_parts.items() if parts}
    cores = {name: "".join(parts) for name, parts in core_parts.items() if parts}
    return base, flare, cores


def render_base_paths(paths: dict[int, str], palette: dict[str, object]) -> str:
    opacities = [0.60, 0.78, 0.87, 0.96, 1.00]
    rendered: list[str] = []
    for level, data in paths.items():
        color = palette["zero"] if level == 0 else palette["levels"][level - 1]  # type: ignore[index]
        rendered.append(
            f'<path data-level="{level}" d="{data}" fill="{color}" '
            f'opacity="{opacities[level]:.2f}"/>'
        )
    return " ".join(rendered)


def render_flare_paths(
    flare_paths: dict[int, str],
    core_paths: dict[str, str],
    palette: dict[str, object],
) -> tuple[str, str]:
    flare_opacities = [0.90, 0.96, 1.00, 1.00]
    flare_rendered: list[str] = []
    for level, data in flare_paths.items():
        color = palette["flare"][level - 1]  # type: ignore[index]
        flare_rendered.append(
            f'<path data-flare-level="{level}" d="{data}" fill="{color}" '
            f'opacity="{flare_opacities[level - 1]:.2f}"/>'
        )

    core_rendered: list[str] = []
    if "mid" in core_paths:
        core_rendered.append(
            f'<path data-flare-core="mid" d="{core_paths["mid"]}" '
            f'fill="{palette["core_mid"]}" opacity="0.98"/>'
        )
    if "high" in core_paths:
        core_rendered.append(
            f'<path data-flare-core="high" d="{core_paths["high"]}" '
            f'fill="{palette["core_high"]}" opacity="1.00"/>'
        )
    return " ".join(flare_rendered), " ".join(core_rendered)


def render_satellite(palette: dict[str, object]) -> str:
    return f'''<g class="satellite" transform="translate(0 {ORBIT_Y:.2f}) scale({SATELLITE_SCALE:.2f})">
      <path d="M-18 0H-12M12 0H18" fill="none" stroke="{palette['body_edge']}" stroke-width="1.8" stroke-linecap="round"/>
      <rect x="-32" y="-8" width="14" height="16" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.1"/>
      <path d="M-27.3-8V8M-22.7-8V8M-32 0H-18" fill="none" stroke="{palette['solar_line']}" stroke-width="0.8" opacity="0.78"/>
      <rect x="18" y="-8" width="14" height="16" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.1"/>
      <path d="M22.7-8V8M27.3-8V8M18 0H32" fill="none" stroke="{palette['solar_line']}" stroke-width="0.8" opacity="0.78"/>
      <rect x="-12" y="-10" width="24" height="20" rx="4" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.5"/>
      <rect x="-8" y="-5" width="4" height="10" rx="1" fill="{palette['detail']}" opacity="0.28"/>
      <rect x="4" y="-5" width="4" height="10" rx="1" fill="{palette['detail']}" opacity="0.28"/>
      <circle cx="0" cy="0" r="4.4" fill="none" stroke="{palette['core']}" stroke-width="1.4"/>
      <circle cx="0" cy="0" r="2.1" fill="{palette['core']}"/>
      <path d="M0-10V-17M-5-20Q0-15 5-20" fill="none" stroke="{palette['body_edge']}" stroke-width="1.3" stroke-linecap="round"/>
      <circle cx="0" cy="-18.7" r="1.4" fill="{palette['core']}"/>
    </g>'''


def render_ground_station(palette: dict[str, object]) -> str:
    x = STATION_X
    y = STATION_Y
    return f'''<g class="ground-station" aria-hidden="true">
      <path d="M{x - 58:.1f} {y - 97:.1f}Q{x - 20:.1f} {y - 126:.1f} {x + 3:.1f} {y - 82:.1f}" fill="none" stroke="{palette['pulse']}" stroke-width="1.1" opacity="0.22" stroke-dasharray="3 6"/>
      <path d="M{x - 43:.1f} {y - 76:.1f}Q{x - 13:.1f} {y - 101:.1f} {x + 4:.1f} {y - 68:.1f}" fill="none" stroke="{palette['pulse']}" stroke-width="1.1" opacity="0.34" stroke-dasharray="3 5"/>
      <path d="M{x - 25:.1f} {y - 55:.1f}Q{x - 7:.1f} {y - 70:.1f} {x + 4:.1f} {y - 50:.1f}" fill="none" stroke="{palette['pulse']}" stroke-width="1.1" opacity="0.50"/>
      <path d="M{x - 12:.1f} {y - 29:.1f}Q{x + 4:.1f} {y - 45:.1f} {x + 20:.1f} {y - 29:.1f}Q{x + 4:.1f} {y - 10:.1f} {x - 12:.1f} {y - 29:.1f}Z" fill="{palette['station_fill']}" stroke="{palette['station']}" stroke-width="1.6"/>
      <path d="M{x + 4:.1f} {y - 29:.1f}L{x + 4:.1f} {y - 5:.1f}M{x - 7:.1f} {y + 8:.1f}H{x + 15:.1f}M{x + 4:.1f} {y - 5:.1f}L{x - 7:.1f} {y + 8:.1f}M{x + 4:.1f} {y - 5:.1f}L{x + 15:.1f} {y + 8:.1f}" fill="none" stroke="{palette['station']}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="{x + 4:.1f}" cy="{y - 29:.1f}" r="2.1" fill="{palette['pulse']}"/>
    </g>'''


def calendar_period(calendar: Calendar) -> tuple[str, str]:
    dates = sorted(day.date for day in flatten_days(calendar))
    if not dates:
        return "unknown", "unknown"
    return dates[0], dates[-1]


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    if theme not in PALETTES:
        raise ValueError(f"unknown theme: {theme}")

    display_calendar = recent_calendar(calendar)
    palette = PALETTES[theme]
    geometry = build_geometry(display_calendar)
    start_date, end_date = calendar_period(display_calendar)
    base_paths, flare_paths, core_paths = build_signal_paths(display_calendar, geometry)
    base_markup = render_base_paths(base_paths, palette)
    flare_markup, core_markup = render_flare_paths(flare_paths, core_paths, palette)

    lane_markup = "".join(
        f'<line x1="{geometry.x0 - 10:.2f}" y1="{y_for_weekday(day, geometry):.2f}" '
        f'x2="{geometry.x1 + 10:.2f}" y2="{y_for_weekday(day, geometry):.2f}" '
        f'stroke="{palette["lane"]}" stroke-width="0.8" opacity="0.28" stroke-dasharray="1 7"/>'
        for day in range(7)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc" shape-rendering="geometricPrecision">
  <title id="title">{escape(login)} contribution telemetry, recent {len(display_calendar.weeks)}-week window</title>
  <desc id="desc">GitHub contribution activity from {escape(start_date)} to {escape(end_date)}, arranged by week and weekday. Signal size and color represent contribution intensity. A decorative CubeSat performs a short telemetry pass over the matrix before a long quiet interval. The full matrix and a static ground station remain available without animation.</desc>
  <style>
    .quiet-sweep {{ transform: translateX({FALLBACK_X:.2f}px); opacity: 1; }}
    .flare-motion {{ animation: telemetry-pass {SCAN_DURATION:.1f}s cubic-bezier(.45,.03,.55,.97) infinite; }}
    .flare-layer, .scan-cues {{ opacity: 1; }}
    @keyframes telemetry-pass {{
      0%, 2% {{ transform: translateX({TRAVEL_START:.2f}px); opacity: 0; visibility: hidden; }}
      5% {{ transform: translateX({TRAVEL_START:.2f}px); opacity: 1; visibility: visible; }}
      31% {{ transform: translateX({TRAVEL_END:.2f}px); opacity: 1; visibility: visible; }}
      35%, 100% {{ transform: translateX({TRAVEL_END:.2f}px); opacity: 0; visibility: hidden; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .quiet-sweep {{ animation: none; transform: translateX({FALLBACK_X:.2f}px); opacity: 1; }}
      .clip-motion {{ animation: none; transform: translateX({FALLBACK_X:.2f}px); }}
      .flare-layer, .scan-cues {{ display: none; }}
    }}
  </style>
  <defs>
    <clipPath id="telemetry-pass-main" clipPathUnits="userSpaceOnUse">
      <rect class="flare-motion clip-motion" visibility="hidden" x="{FLARE_MAIN_X:.2f}" y="{CLIP_TOP:.2f}" width="{FLARE_MAIN_WIDTH:.2f}" height="{CLIP_BOTTOM - CLIP_TOP:.2f}" transform="translate({FALLBACK_X:.2f} 0)"/>
    </clipPath>
    <clipPath id="telemetry-pass-core" clipPathUnits="userSpaceOnUse">
      <rect class="flare-motion clip-motion" visibility="hidden" x="{FLARE_CORE_X:.2f}" y="{CLIP_TOP - 3:.2f}" width="{FLARE_CORE_WIDTH:.2f}" height="{CLIP_BOTTOM - CLIP_TOP + 6:.2f}" transform="translate({FALLBACK_X:.2f} 0)"/>
    </clipPath>
  </defs>
  <g aria-hidden="true">
    <path d="M{geometry.x0 - 4:.2f} {ORBIT_Y:.2f}H{geometry.x1 + 4:.2f}" fill="none" stroke="{palette['track']}" stroke-width="1" opacity="0.34" stroke-dasharray="2 8"/>
    <circle cx="{geometry.x0:.2f}" cy="{ORBIT_Y:.2f}" r="2.5" fill="none" stroke="{palette['track']}" stroke-width="1" opacity="0.48"/>
    <path d="M{geometry.x1 - 4:.2f} {ORBIT_Y:.2f}L{geometry.x1:.2f} {ORBIT_Y - 4:.2f}L{geometry.x1 + 4:.2f} {ORBIT_Y:.2f}L{geometry.x1:.2f} {ORBIT_Y + 4:.2f}Z" fill="{palette['track']}" opacity="0.58"/>
    <g class="telemetry-lanes">{lane_markup}</g>
    <g class="signal-matrix">{base_markup}</g>
    <g class="flare-layer flare-main" clip-path="url(#telemetry-pass-main)" opacity="0">{flare_markup}</g>
    <g class="flare-layer flare-cores" clip-path="url(#telemetry-pass-core)" opacity="0">{core_markup}</g>
    {render_ground_station(palette)}
    <g class="quiet-sweep flare-motion" transform="translate({FALLBACK_X:.2f} 0)" opacity="1">
      <g class="scan-cues" opacity="0">
        <line class="scan-line" x1="0" y1="{ORBIT_Y + 20:.2f}" x2="0" y2="{CLIP_TOP - 1:.2f}" stroke="{palette['scan']}" stroke-width="1.1" opacity="0.58" vector-effect="non-scaling-stroke"/>
        <path class="scan-beam" d="M0 {ORBIT_Y + 18:.2f}L-18 {CLIP_TOP:.2f}M0 {ORBIT_Y + 18:.2f}L18 {CLIP_TOP:.2f}" fill="none" stroke="{palette['beam']}" stroke-width="0.9" stroke-linecap="round" opacity="0.30" vector-effect="non-scaling-stroke"/>
      </g>
      {render_satellite(palette)}
    </g>
  </g>
</svg>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("GITHUB_USER", "DavCalo"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--demo", action="store_true", help="Generate deterministic preview data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.demo:
        calendar = demo_calendar()
    else:
        if not args.token:
            print("error: GITHUB_TOKEN is required unless --demo is used", file=sys.stderr)
            return 2
        calendar = fetch_calendar(args.user, args.token)

    display_calendar = recent_calendar(calendar)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "contribution-scan.svg").write_text(
        render_svg(calendar, args.user, "light"), encoding="utf-8"
    )
    (args.output / "contribution-scan-dark.svg").write_text(
        render_svg(calendar, args.user, "dark"), encoding="utf-8"
    )
    print(
        f"Generated contribution telemetry for {args.user}: "
        f"{display_calendar.contributions} contributions across "
        f"{len(display_calendar.weeks)} weeks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
