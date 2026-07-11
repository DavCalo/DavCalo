#!/usr/bin/env python3
"""Generate an animated recent GitHub contribution telemetry scan as SVG.

The horizontal axis is time (weeks), the vertical axis is weekday, and signal
size/brightness represents contribution intensity. The latest 26 weeks are
expanded across the canvas. A CubeSat performs one left-to-right pass, briefly
turning active days into larger circles or technical four-point signal flares.
The complete contribution matrix remains static and continuously visible.

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
HEIGHT = 215
GRID_X0 = 48.0
GRID_X1 = 672.0
GRID_Y0 = 82.0
GRID_ROW_GAP = 15.0
RECENT_WEEK_LIMIT = 26
SATELLITE_Y = 44.0
SATELLITE_SCALE = 0.97
SCAN_DURATION = 21.0
TRAVEL_START = GRID_X0
TRAVEL_END = GRID_X1
FALLBACK_X = GRID_X1 - 4.0
CLIP_TOP = 75.0
CLIP_BOTTOM = 179.0


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


PALETTES = {
    "light": {
        "zero": "#B8C4D1",
        "levels": ["#5A8FA8", "#287FA5", "#176B91", "#4F46E5"],
        "flare": ["#4A91AC", "#269AC0", "#2F83B5", "#7277EE"],
        "core_mid": "#D5F0F7",
        "core_high": "#E0E7FF",
        "marker": "#94A3B8",
        "scan": "#287FA5",
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
        "flare": ["#5AA5BA", "#61BED8", "#7DD3FC", "#C7D2FE"],
        "core_mid": "#D9F2F8",
        "core_high": "#E0E7FF",
        "marker": "#64748B",
        "scan": "#7DD3FC",
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


def recent_calendar(calendar: Calendar, week_limit: int = RECENT_WEEK_LIMIT) -> Calendar:
    """Return a new calendar containing the latest chronological weeks."""
    if week_limit <= 0:
        raise ValueError("week_limit must be positive")
    selected_weeks = [list(week) for week in calendar.weeks[-week_limit:]]
    total = sum(day.count for week in selected_weeks for day in week)
    return Calendar(total=total, weeks=selected_weeks, demo=calendar.demo)


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


def star_subpath(x: float, y: float, outer_radius: float, inner_radius: float) -> str:
    """Return a deterministic, symmetric four-point signal flare."""
    points: list[tuple[float, float]] = []
    for index in range(8):
        angle = -math.pi / 2 + index * math.pi / 4
        radius = outer_radius if index % 2 == 0 else inner_radius
        points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius))
    commands = [f"M{points[0][0]:.2f},{points[0][1]:.2f}"]
    commands.extend(f"L{px:.2f},{py:.2f}" for px, py in points[1:])
    commands.append("Z")
    return "".join(commands)


def build_signal_paths(
    calendar: Calendar,
    geometry: Geometry,
) -> tuple[dict[int, str], dict[int, str], dict[str, str]]:
    max_count = max((day.count for day in flatten_days(calendar)), default=0)
    base_radii = [1.70, 2.30, 2.90, 3.55, 4.20]
    flare_radii = {1: 2.70 * 1.06, 2: 3.70 * 1.08}
    star_sizes = {3: (6.80 * 1.10, 2.45 * 1.10), 4: (8.00 * 1.10, 2.85 * 1.10)}

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
                outer, inner = star_sizes[level]
                flare_parts[level].append(star_subpath(x, y, outer, inner))

            if level in (2, 3):
                core_parts["mid"].append(circle_subpath(x, y, 1.32))
            elif level == 4:
                core_parts["high"].append(circle_subpath(x, y, 1.87))
                core_parts["high"].append(star_subpath(x, y, 3.30, 1.16))

    base = {level: "".join(parts) for level, parts in base_parts.items() if parts}
    flare = {level: "".join(parts) for level, parts in flare_parts.items() if parts}
    cores = {name: "".join(parts) for name, parts in core_parts.items() if parts}
    return base, flare, cores


def render_base_paths(
    paths: dict[int, str],
    palette: dict[str, object],
) -> str:
    opacities = [0.72, 0.78, 0.86, 0.94, 1.00]
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
    flare_opacities = [0.92, 0.97, 1.00, 1.00]
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
    return f'''<g class="satellite" transform="translate(0 {SATELLITE_Y:.2f}) scale({SATELLITE_SCALE:.2f})">
        <path d="M-20 0H-13M13 0H20" fill="none" stroke="{palette['body_edge']}" stroke-width="1.8" stroke-linecap="round"/>
        <rect x="-36" y="-9" width="16" height="18" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.1"/>
        <path d="M-30.7-9V9M-25.3-9V9M-36 0H-20" fill="none" stroke="{palette['solar_line']}" stroke-width="0.8" opacity="0.80"/>
        <rect x="20" y="-9" width="16" height="18" rx="2" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.1"/>
        <path d="M25.3-9V9M30.7-9V9M20 0H36" fill="none" stroke="{palette['solar_line']}" stroke-width="0.8" opacity="0.80"/>
        <rect x="-13" y="-11" width="26" height="22" rx="4.5" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.5"/>
        <path d="M-8-11L-5-15H5L8-11" fill="none" stroke="{palette['body_edge']}" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="-10" y="-6" width="4" height="12" rx="1.2" fill="{palette['detail']}" opacity="0.30"/>
        <rect x="6" y="-6" width="4" height="12" rx="1.2" fill="{palette['detail']}" opacity="0.30"/>
        <circle cx="0" cy="0" r="4.8" fill="none" stroke="{palette['core']}" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="2.4" fill="{palette['core']}"/>
        <path d="M0-15V-22M-6-25Q0-19 6-25" fill="none" stroke="{palette['body_edge']}" stroke-width="1.4" stroke-linecap="round"/>
        <circle cx="0" cy="-23.2" r="1.6" fill="{palette['core']}"/>
        <path d="M-6 7H6" fill="none" stroke="{palette['detail']}" stroke-width="1.1" stroke-linecap="round" opacity="0.68"/>
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

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc" shape-rendering="geometricPrecision">
  <title id="title">{escape(login)} Signal Flare Strong, recent {len(display_calendar.weeks)}-week contribution calendar, {escape(start_date)} to {escape(end_date)}</title>
  <desc id="desc">GitHub contribution activity from the latest {len(display_calendar.weeks)} weeks, {escape(start_date)} to {escape(end_date)}, arranged with weeks from left to right and weekdays from top to bottom. Larger and more strongly colored circles indicate higher contribution intensity. During the decorative satellite pass, active signals temporarily become larger circles or technical four-point flares with brighter centers, while the complete base calendar remains static and continuously visible.</desc>
  <style>
    .quiet-sweep {{ transform: translateX({FALLBACK_X:.2f}px); opacity: 1; }}
    .flare-motion {{ animation: signal-flare {SCAN_DURATION:.1f}s linear infinite; }}
    .flare-layer, .scan-cues {{ opacity: 1; }}
    @keyframes signal-flare {{
      0%, 0.5% {{ transform: translateX({TRAVEL_START:.2f}px); opacity: 0; visibility: hidden; }}
      2.5% {{ transform: translateX({TRAVEL_START:.2f}px); opacity: 1; visibility: visible; }}
      72.5% {{ transform: translateX({TRAVEL_END:.2f}px); opacity: 1; visibility: visible; }}
      77.5%, 100% {{ transform: translateX({TRAVEL_END:.2f}px); opacity: 0; visibility: hidden; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .quiet-sweep {{ animation: none; transform: translateX({FALLBACK_X:.2f}px); opacity: 1; }}
      .clip-motion {{ animation: none; transform: translateX({FALLBACK_X:.2f}px); }}
      .flare-layer, .scan-cues {{ display: none; }}
    }}
  </style>
  <defs>
    <clipPath id="sf-signal-flare-strong-main" clipPathUnits="userSpaceOnUse">
      <rect class="flare-motion clip-motion" visibility="hidden" x="-14" y="{CLIP_TOP:.2f}" width="28" height="{CLIP_BOTTOM - CLIP_TOP:.2f}" transform="translate({FALLBACK_X:.2f} 0)"/>
    </clipPath>
    <clipPath id="sf-signal-flare-strong-core" clipPathUnits="userSpaceOnUse">
      <rect class="flare-motion clip-motion" visibility="hidden" x="-5" y="{CLIP_TOP - 4:.2f}" width="10" height="{CLIP_BOTTOM - CLIP_TOP + 8:.2f}" transform="translate({FALLBACK_X:.2f} 0)"/>
    </clipPath>
  </defs>
  <g aria-hidden="true">
    <g class="terminal-markers" fill="none" stroke="{palette['marker']}" stroke-width="1" opacity="0.38">
      <circle cx="{geometry.x0:.2f}" cy="61" r="2.4"/><circle cx="{geometry.x1:.2f}" cy="61" r="2.4"/>
    </g>
    <g class="signal-matrix">{base_markup}</g>
    <g class="flare-layer flare-main" clip-path="url(#sf-signal-flare-strong-main)" opacity="0">{flare_markup}</g>
    <g class="flare-layer flare-cores" clip-path="url(#sf-signal-flare-strong-core)" opacity="0">{core_markup}</g>
    <g class="quiet-sweep flare-motion" transform="translate({FALLBACK_X:.2f} 0)" opacity="1">
      <g class="scan-cues" opacity="0">
        <line class="scan-line" x1="0" y1="56" x2="0" y2="76" stroke="{palette['scan']}" stroke-width="1" opacity="0.44"/>
        <path d="M-3.5 77H3.5M-3.5 181H3.5" fill="none" stroke="{palette['scan']}" stroke-width="1" stroke-linecap="round" opacity="0.48"/>
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

    display_calendar = recent_calendar(calendar)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "contribution-scan.svg").write_text(
        render_svg(calendar, args.user, "light"), encoding="utf-8"
    )
    (args.output / "contribution-scan-dark.svg").write_text(
        render_svg(calendar, args.user, "dark"), encoding="utf-8"
    )
    print(
        f"Generated recent contribution scan for {args.user}: "
        f"{display_calendar.total} contributions across {len(display_calendar.weeks)} weeks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
