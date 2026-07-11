#!/usr/bin/env python3
"""Generate an animated GitHub contribution satellite scan as SVG.

The horizontal axis is time (weeks), the vertical axis is weekday, and signal
size/brightness represents contribution intensity. A CubeSat performs a single
left-to-right scan over the year, fades out at the edge, and restarts invisibly
from the left. There is no return trajectory and no data-driven vertical
movement.

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

WIDTH = 720
HEIGHT = 252
GRID_X0 = 48.0
GRID_X1 = 672.0
GRID_Y0 = 84.0
GRID_ROW_GAP = 15.0
SATELLITE_Y = 48.0
SATELLITE_SCALE = 0.98
SCAN_DURATION = 28.0


@dataclass(frozen=True)
class Day:
    date: str
    weekday: int
    count: int


@dataclass(frozen=True)
class Calendar:
    total: int
    weeks: list[list[Day]]
    demo: bool = False


@dataclass(frozen=True)
class Geometry:
    week_count: int
    x0: float = GRID_X0
    x1: float = GRID_X1
    y0: float = GRID_Y0
    row_gap: float = GRID_ROW_GAP

    @property
    def scan_top(self) -> float:
        return self.y0 - 16.0

    @property
    def scan_bottom(self) -> float:
        return self.y0 + 6 * self.row_gap + 16.0


PALETTES = {
    "light": {
        "zero": "#B8C4D1",
        "levels": ["#5A8FA8", "#287FA5", "#176B91", "#4F46E5"],
        "orbit": "#64748B",
        "orbit_soft": "#94A3B8",
        "orbit_faint": "#CBD5E1",
        "beam": "#176B91",
        "scan_band": "#38A3C7",
        "scan_edge": "#287FA5",
        "body": "#F8FAFC",
        "body_edge": "#334155",
        "solar": "#287FA5",
        "solar_edge": "#D9F0F7",
        "solar_line": "#BAE6FD",
        "core": "#4F46E5",
        "detail": "#64748B",
    },
    "dark": {
        "zero": "#3F4D61",
        "levels": ["#3C7A91", "#2F9CC2", "#55A8C5", "#A5B4FC"],
        "orbit": "#64748B",
        "orbit_soft": "#475569",
        "orbit_faint": "#334155",
        "beam": "#55A8C5",
        "scan_band": "#55A8C5",
        "scan_edge": "#A5B4FC",
        "body": "#E2E8F0",
        "body_edge": "#94A3B8",
        "solar": "#2F9CC2",
        "solar_edge": "#BAE6FD",
        "solar_line": "#BAE6FD",
        "core": "#A5B4FC",
        "detail": "#94A3B8",
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
            "User-Agent": "contribution-orbit-generator",
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
    weeks: list[list[Day]] = []
    for raw_week in raw["weeks"]:
        weeks.append([
            Day(
                date=item["date"],
                weekday=int(item["weekday"]),
                count=int(item["contributionCount"]),
            )
            for item in raw_week["contributionDays"]
        ])
    return Calendar(total=int(raw["totalContributions"]), weeks=weeks)


def demo_calendar(reference_date: date | None = None) -> Calendar:
    rng = random.Random(20260710)
    end = reference_date or date.today()
    start = end - timedelta(days=365)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    day_count = (end - start).days + 1
    counts: list[int] = []
    for index in range(day_count):
        # Seeded counts are repeatable for a fixed reference date.
        phase = 0.13 + 0.07 * (1 + math.sin(index / 25.0))
        burst = 0.12 if 0.39 * day_count < index < 0.62 * day_count else 0.0
        if rng.random() >= phase + burst:
            counts.append(0)
            continue
        amount = 1 + int(rng.expovariate(0.42))
        if rng.random() < 0.07:
            amount += rng.randint(6, 16)
        counts.append(min(amount, 30))

    weeks: list[list[Day]] = []
    for index, count in enumerate(counts):
        current = start + timedelta(days=index)
        weekday = (current.weekday() + 1) % 7
        if weekday == 0 or not weeks:
            weeks.append([])
        weeks[-1].append(Day(current.isoformat(), weekday, count))
    return Calendar(total=sum(counts), weeks=weeks, demo=True)


def flatten_days(calendar: Calendar) -> list[Day]:
    return [day for week in calendar.weeks for day in week]


def level_for(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    # Log scaling keeps ordinary activity distinguishable when one day is extreme.
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


def render_signal_paths(
    calendar: Calendar,
    geometry: Geometry,
    palette: dict[str, object],
) -> str:
    max_count = max((day.count for day in flatten_days(calendar)), default=0)
    radii = [1.70, 2.30, 2.90, 3.55, 4.20]
    opacities = [0.72, 0.78, 0.86, 0.94, 1.0]
    paths: list[list[str]] = [[] for _ in range(5)]

    for week_index, week in enumerate(calendar.weeks):
        x = x_for_week(week_index, geometry)
        for day in week:
            level = level_for(day.count, max_count)
            paths[level].append(
                circle_subpath(x, y_for_weekday(day.weekday, geometry), radii[level])
            )

    rendered: list[str] = []
    for level, subpaths in enumerate(paths):
        if not subpaths:
            continue
        color = palette["zero"] if level == 0 else palette["levels"][level - 1]  # type: ignore[index]
        rendered.append(
            f'<path data-level="{level}" d="{"".join(subpaths)}" '
            f'fill="{color}" opacity="{opacities[level]:.2f}"/>'
        )
    return "\n    ".join(rendered)


def render_satellite(palette: dict[str, object]) -> str:
    return f'''<g class="satellite" transform="translate(0 {SATELLITE_Y:.2f}) scale({SATELLITE_SCALE:.2f})">
        <path d="M-23 0H-15M15 0H23" fill="none" stroke="{palette['body_edge']}" stroke-width="2" stroke-linecap="round"/>
        <rect x="-41" y="-10" width="18" height="20" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.2"/>
        <path d="M-35-10V10M-29-10V10M-41 0H-23" fill="none" stroke="{palette['solar_line']}" stroke-width="0.9" opacity="0.82"/>
        <rect x="23" y="-10" width="18" height="20" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.2"/>
        <path d="M29-10V10M35-10V10M23 0H41" fill="none" stroke="{palette['solar_line']}" stroke-width="0.9" opacity="0.82"/>
        <rect x="-15" y="-12" width="30" height="24" rx="5" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.6"/>
        <path d="M-10-12L-6-17H6L10-12" fill="none" stroke="{palette['body_edge']}" stroke-width="1.4" stroke-linejoin="round"/>
        <rect x="-12" y="-7" width="5" height="14" rx="1.5" fill="{palette['detail']}" opacity="0.34"/>
        <rect x="7" y="-7" width="5" height="14" rx="1.5" fill="{palette['detail']}" opacity="0.34"/>
        <circle cx="0" cy="0" r="5" fill="none" stroke="{palette['core']}" stroke-width="1.6"/>
        <circle cx="0" cy="0" r="2.5" fill="{palette['core']}"/>
        <path d="M0-17V-25M-7-28Q0-21 7-28" fill="none" stroke="{palette['body_edge']}" stroke-width="1.5" stroke-linecap="round"/>
        <circle cx="0" cy="-26" r="1.8" fill="{palette['core']}"/>
        <path d="M-7 8H7" fill="none" stroke="{palette['detail']}" stroke-width="1.2" stroke-linecap="round" opacity="0.72"/>
      </g>'''


def render_orbital_frame(
    geometry: Geometry,
    palette: dict[str, object],
) -> str:
    timeline_y = HEIGHT - 34.0
    return f'''<g class="orbital-frame" aria-hidden="true">
      <path d="M18 184C130 12 590 4 704 100" fill="none" stroke="{palette['orbit']}" stroke-width="1.2" stroke-linecap="round" opacity="0.24"/>
      <path d="M52 222C214 263 506 252 686 204" fill="none" stroke="{palette['orbit_soft']}" stroke-width="1" stroke-linecap="round" stroke-dasharray="3 10" opacity="0.30"/>
      <circle cx="31" cy="175" r="3" fill="none" stroke="{palette['orbit']}" stroke-width="1.2" opacity="0.52"/>
      <circle cx="690" cy="166" r="3" fill="{palette['orbit']}" opacity="0.46"/>
      <path d="M30 68H72M648 68H690" fill="none" stroke="{palette['orbit_faint']}" stroke-width="1" stroke-linecap="round" opacity="0.48"/>
      <path d="M{geometry.x0:.2f} {timeline_y:.2f}H{geometry.x1 - 11:.2f}M{geometry.x1 - 11:.2f} {timeline_y:.2f}L{geometry.x1 - 19:.2f} {timeline_y - 4:.2f}M{geometry.x1 - 11:.2f} {timeline_y:.2f}L{geometry.x1 - 19:.2f} {timeline_y + 4:.2f}" fill="none" stroke="{palette['orbit']}" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" opacity="0.46"/>
    </g>'''


def render_scan(
    geometry: Geometry,
    palette: dict[str, object],
) -> str:
    band_width = 18.0
    band_x = -band_width / 2
    band_height = geometry.scan_bottom - geometry.scan_top
    return f'''<rect class="scan-band" x="{band_x:.2f}" y="{geometry.scan_top:.2f}" width="{band_width:.2f}" height="{band_height:.2f}" fill="{palette['scan_band']}" opacity="0.08"/>
      <path class="scan-edge" d="M{band_x:.2f} {geometry.scan_top:.2f}V{geometry.scan_bottom:.2f}M{-band_x:.2f} {geometry.scan_top:.2f}V{geometry.scan_bottom:.2f}" fill="none" stroke="{palette['scan_edge']}" stroke-width="0.8" opacity="0.20"/>
      <line class="scan-line" x1="0" y1="{geometry.scan_top:.2f}" x2="0" y2="{geometry.scan_bottom:.2f}" stroke="{palette['beam']}" stroke-width="1.4" opacity="0.58" vector-effect="non-scaling-stroke"/>'''


def calendar_period(calendar: Calendar) -> tuple[str, str]:
    dates = sorted(day.date for day in flatten_days(calendar))
    if not dates:
        return "unknown", "unknown"
    return dates[0], dates[-1]


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    if theme not in PALETTES:
        raise ValueError(f"unknown theme: {theme}")

    palette = PALETTES[theme]
    geometry = build_geometry(calendar)
    start_date, end_date = calendar_period(calendar)
    signal_paths = render_signal_paths(calendar, geometry, palette)
    travel_start = geometry.x0 - 20.0
    travel_end = geometry.x1 + 20.0
    reduced_x = geometry.x1 - 2.0

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc" shape-rendering="geometricPrecision">
  <title id="title">{escape(login)} Quiet Sweep Orbital Frame contribution calendar, {escape(start_date)} to {escape(end_date)}</title>
  <desc id="desc">GitHub contribution activity arranged chronologically with weeks from left to right and weekdays from top to bottom. Larger, more opaque, and more strongly colored circles indicate higher contribution activity; faint circles indicate days without contributions. Open orbital arcs and a slow satellite sweep are decorative, while all contribution signals remain static and continuously visible.</desc>
  <style>
    .quiet-sweep {{
      transform: translateX({reduced_x:.2f}px);
      opacity: 1;
      animation: quiet-sweep {SCAN_DURATION:.1f}s linear infinite;
    }}
    @keyframes quiet-sweep {{
      0%, 8% {{ transform: translateX({travel_start:.2f}px); opacity: 0; }}
      11% {{ transform: translateX({travel_start:.2f}px); opacity: 1; }}
      77% {{ transform: translateX({travel_end:.2f}px); opacity: 1; }}
      83%, 100% {{ transform: translateX({travel_end:.2f}px); opacity: 0; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .quiet-sweep {{ animation: none; transform: translateX({reduced_x:.2f}px); opacity: 1; }}
      .scan-line {{ display: none; }}
      .scan-band, .scan-edge {{ display: none; }}
    }}
  </style>
  <g aria-hidden="true">
    {render_orbital_frame(geometry, palette)}
    <g class="signal-matrix">
      {signal_paths}
    </g>
    <g class="quiet-sweep" transform="translate({reduced_x:.2f} 0)" opacity="1">
      {render_scan(geometry, palette)}
      {render_satellite(palette)}
    </g>
  </g>
</svg>
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("GITHUB_USER", "DavCalo"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--demo", action="store_true", help="Generate seeded preview data without GitHub")
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

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "contribution-scan.svg").write_text(render_svg(calendar, args.user, "light"), encoding="utf-8")
    (args.output / "contribution-scan-dark.svg").write_text(render_svg(calendar, args.user, "dark"), encoding="utf-8")
    print(f"Generated contribution scan for {args.user}: {calendar.total} contributions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
