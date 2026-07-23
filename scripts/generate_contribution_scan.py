#!/usr/bin/env python3
"""Generate an animated GitHub contribution constellation as accessible SVG.

The latest 26 contribution weeks become a field of signals and stars. A CubeSat
crosses the scene, revealing brighter flares around active days while a quiet
space backdrop and a static fallback keep the graphic readable without motion.
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

WIDTH = 1100
HEIGHT = 300
GRID_X0 = 72.0
GRID_X1 = 900.0
GRID_Y0 = 122.0
GRID_ROW_GAP = 22.0
RECENT_WEEK_LIMIT = 26
ORBIT_Y = 78.0
SATELLITE_SCALE = 0.98
CYCLE_DURATION = 24.0
TRAVEL_START = GRID_X0
TRAVEL_END = GRID_X1
FALLBACK_X = GRID_X1 - 30.0
CLIP_TOP = 103.0
CLIP_BOTTOM = 266.0
FLARE_MAIN_X = -42.0
FLARE_MAIN_WIDTH = 84.0
FLARE_CORE_X = -8.0
FLARE_CORE_WIDTH = 16.0


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
        "bg0": "#F7FAFF",
        "bg1": "#E9F1FF",
        "panel": "#FFFFFF",
        "edge": "#B9CAE6",
        "text": "#0F172A",
        "muted": "#5A6A83",
        "zero": "#B9C7DA",
        "levels": ["#3C98B2", "#0F8DB4", "#2563EB", "#7C3AED"],
        "flare": ["#22D3EE", "#38BDF8", "#818CF8", "#E879F9"],
        "core_mid": "#FFFFFF",
        "core_high": "#FFF7FF",
        "orbit": "#64748B",
        "lane": "#B8C7DE",
        "beam": "#38BDF8",
        "trail": "#7C3AED",
        "body": "#FFFFFF",
        "body_edge": "#52617D",
        "solar": "#2563EB",
        "solar_edge": "#67E8F9",
        "solar_line": "#BAE6FD",
        "core": "#DB2777",
        "planet": "#E2E8FF",
        "planet_edge": "#A5B4FC",
        "glow_a": "#7C3AED",
        "glow_b": "#0891B2",
        "star": ["#0891B2", "#2563EB", "#7C3AED", "#DB2777", "#64748B"],
    },
    "dark": {
        "bg0": "#050816",
        "bg1": "#0B1028",
        "panel": "#0F1736",
        "edge": "#2A3B68",
        "text": "#F8FAFC",
        "muted": "#9EACCA",
        "zero": "#33415C",
        "levels": ["#2D7E95", "#22A7C8", "#60A5FA", "#A78BFA"],
        "flare": ["#67E8F9", "#7DD3FC", "#A5B4FC", "#F0ABFC"],
        "core_mid": "#E6FBFF",
        "core_high": "#FFF4FF",
        "orbit": "#6B7A9D",
        "lane": "#263554",
        "beam": "#22D3EE",
        "trail": "#A78BFA",
        "body": "#E8EEFF",
        "body_edge": "#9EACCF",
        "solar": "#2563EB",
        "solar_edge": "#67E8F9",
        "solar_line": "#BAE6FD",
        "core": "#EC4899",
        "planet": "#151F48",
        "planet_edge": "#6677B8",
        "glow_a": "#7C3AED",
        "glow_b": "#22D3EE",
        "star": ["#22D3EE", "#60A5FA", "#A78BFA", "#EC4899", "#E2E8F0"],
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
            "User-Agent": "contribution-constellation-generator",
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
    rng = random.Random(20260804)
    end = reference_date or date.today()
    start = end - timedelta(days=365)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    day_count = (end - start).days + 1

    counts: list[int] = []
    for index in range(day_count):
        phase = 0.14 + 0.08 * (1 + math.sin(index / 21.0))
        burst = 0.18 if 0.42 * day_count < index < 0.72 * day_count else 0.0
        if rng.random() >= phase + burst:
            counts.append(0)
            continue
        amount = 1 + int(rng.expovariate(0.42))
        if rng.random() < 0.10:
            amount += rng.randint(6, 18)
        counts.append(min(amount, 32))

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


def x_for_week(week_index: int, geometry: Geometry) -> float:
    if geometry.week_count <= 1:
        return (geometry.x0 + geometry.x1) / 2
    return geometry.x0 + week_index * ((geometry.x1 - geometry.x0) / (geometry.week_count - 1))


def y_for_weekday(weekday: int, geometry: Geometry) -> float:
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday must be between 0 and 6, got {weekday}")
    return geometry.y0 + weekday * geometry.row_gap


def circle_path(x: float, y: float, radius: float) -> str:
    return (
        f"M{x - radius:.2f},{y:.2f}"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {2 * radius:.2f},0"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {-2 * radius:.2f},0Z"
    )


def diamond_path(x: float, y: float, radius: float) -> str:
    return (
        f"M{x:.2f},{y - radius:.2f}L{x + radius:.2f},{y:.2f}"
        f"L{x:.2f},{y + radius:.2f}L{x - radius:.2f},{y:.2f}Z"
    )


def star_path(x: float, y: float, outer: float, inner: float) -> str:
    points: list[tuple[float, float]] = []
    for index in range(8):
        angle = -math.pi / 2 + index * math.pi / 4
        radius = outer if index % 2 == 0 else inner
        points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius))
    commands = [f"M{points[0][0]:.2f},{points[0][1]:.2f}"]
    commands.extend(f"L{px:.2f},{py:.2f}" for px, py in points[1:])
    commands.append("Z")
    return "".join(commands)


def build_signal_paths(calendar: Calendar, geometry: Geometry) -> tuple[dict[int, str], dict[int, str], dict[str, str]]:
    max_count = max((day.count for day in flatten_days(calendar)), default=0)
    base_parts: dict[int, list[str]] = {level: [] for level in range(5)}
    flare_parts: dict[int, list[str]] = {level: [] for level in range(1, 5)}
    core_parts: dict[str, list[str]] = {"mid": [], "high": []}

    for week_index, week in enumerate(calendar.weeks):
        x = x_for_week(week_index, geometry)
        for day in week:
            y = y_for_weekday(day.weekday, geometry)
            level = level_for(day.count, max_count)
            if level == 0:
                base_parts[level].append(circle_path(x, y, 1.35))
            elif level == 1:
                base_parts[level].append(circle_path(x, y, 2.25))
                flare_parts[level].append(circle_path(x, y, 4.2))
            elif level == 2:
                base_parts[level].append(diamond_path(x, y, 3.2))
                flare_parts[level].append(diamond_path(x, y, 6.2))
                core_parts["mid"].append(circle_path(x, y, 1.2))
            elif level == 3:
                base_parts[level].append(star_path(x, y, 5.2, 1.8))
                flare_parts[level].append(star_path(x, y, 9.2, 2.7))
                core_parts["mid"].append(circle_path(x, y, 1.7))
            else:
                base_parts[level].append(star_path(x, y, 7.3, 2.2))
                flare_parts[level].append(star_path(x, y, 12.0, 3.2))
                core_parts["high"].append(circle_path(x, y, 2.4))
                core_parts["high"].append(star_path(x, y, 4.3, 1.2))

    base = {level: "".join(parts) for level, parts in base_parts.items() if parts}
    flare = {level: "".join(parts) for level, parts in flare_parts.items() if parts}
    cores = {name: "".join(parts) for name, parts in core_parts.items() if parts}
    return base, flare, cores


def render_paths(paths: dict[int, str], palette: dict[str, object], flare: bool = False) -> str:
    rendered: list[str] = []
    if flare:
        for level, data in paths.items():
            color = palette["flare"][level - 1]  # type: ignore[index]
            rendered.append(
                f'<path data-flare-level="{level}" d="{data}" fill="{color}" opacity="1" filter="url(#signal-glow)"/>'
            )
    else:
        opacities = [0.42, 0.82, 0.91, 0.98, 1.0]
        for level, data in paths.items():
            color = palette["zero"] if level == 0 else palette["levels"][level - 1]  # type: ignore[index]
            filter_attr = ' filter="url(#small-glow)"' if level >= 3 else ""
            rendered.append(
                f'<path data-level="{level}" d="{data}" fill="{color}" opacity="{opacities[level]:.2f}"{filter_attr}/>'
            )
    return "".join(rendered)


def render_cores(paths: dict[str, str], palette: dict[str, object]) -> str:
    parts: list[str] = []
    if "mid" in paths:
        parts.append(f'<path data-flare-core="mid" d="{paths["mid"]}" fill="{palette["core_mid"]}"/>')
    if "high" in paths:
        parts.append(f'<path data-flare-core="high" d="{paths["high"]}" fill="{palette["core_high"]}"/>')
    return "".join(parts)


def render_satellite(palette: dict[str, object]) -> str:
    return f'''<g class="satellite-body" transform="scale({SATELLITE_SCALE:.2f})">
      <path d="M-23 0H-14M14 0H23" stroke="{palette['body_edge']}" stroke-width="2" stroke-linecap="round"/>
      <rect x="-51" y="-14" width="28" height="28" rx="4" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.5"/>
      <path d="M-41.7-14V14M-32.3-14V14M-51 0H-23" stroke="{palette['solar_line']}" stroke-width="1" opacity=".75"/>
      <rect x="23" y="-14" width="28" height="28" rx="4" fill="{palette['solar']}" stroke="{palette['solar_edge']}" stroke-width="1.5"/>
      <path d="M32.3-14V14M41.7-14V14M23 0H51" stroke="{palette['solar_line']}" stroke-width="1" opacity=".75"/>
      <rect x="-14" y="-17" width="28" height="34" rx="6" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.8"/>
      <circle cx="0" cy="0" r="7" fill="none" stroke="{palette['trail']}" stroke-width="2"/>
      <circle cx="0" cy="0" r="3.2" fill="{palette['core']}"/>
      <path d="M0-17V-31M-8-36Q0-27 8-36" fill="none" stroke="{palette['body_edge']}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="0" cy="-33" r="2.3" fill="{palette['beam']}"/>
    </g>'''


def background_stars(palette: dict[str, object], theme: str) -> str:
    rng = random.Random(9091 if theme == "dark" else 9092)
    colors = palette["star"]  # type: ignore[assignment]
    parts: list[str] = []
    for _ in range(48):
        x = rng.uniform(20, WIDTH - 20)
        y = rng.uniform(20, HEIGHT - 20)
        r = rng.choice([0.6, 0.8, 1.0, 1.3, 1.7])
        opacity = rng.uniform(0.12, 0.50)
        duration = rng.uniform(3.0, 7.0)
        delay = rng.uniform(-6.0, 0.0)
        color = rng.choice(colors)
        parts.append(
            f'<circle class="twinkle" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" '
            f'opacity="{opacity:.2f}" style="animation-duration:{duration:.2f}s;animation-delay:{delay:.2f}s"/>'
        )
    return "".join(parts)


def calendar_period(calendar: Calendar) -> tuple[str, str]:
    dates = sorted(day.date for day in flatten_days(calendar))
    if not dates:
        return "unknown", "unknown"
    return dates[0], dates[-1]


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    if theme not in PALETTES:
        raise ValueError(f"unknown theme: {theme}")

    display = recent_calendar(calendar)
    palette = PALETTES[theme]
    geometry = Geometry(week_count=max(1, len(display.weeks)))
    start_date, end_date = calendar_period(display)
    base_paths, flare_paths, core_paths = build_signal_paths(display, geometry)
    base_markup = render_paths(base_paths, palette)
    flare_markup = render_paths(flare_paths, palette, flare=True)
    core_markup = render_cores(core_paths, palette)
    stars = background_stars(palette, theme)
    lanes = "".join(
        f'<line x1="{geometry.x0 - 10:.1f}" y1="{y_for_weekday(day, geometry):.1f}" '
        f'x2="{geometry.x1 + 10:.1f}" y2="{y_for_weekday(day, geometry):.1f}" '
        f'stroke="{palette["lane"]}" stroke-width=".8" opacity=".32" stroke-dasharray="1 8"/>'
        for day in range(7)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(login)} contribution constellation, latest {len(display.weeks)} weeks</title>
  <desc id="desc">GitHub contribution activity from {escape(start_date)} to {escape(end_date)} rendered as stars and signals. A CubeSat crosses the constellation and briefly amplifies active days. The static scene remains readable without animation.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{palette['bg0']}"/><stop offset="1" stop-color="{palette['bg1']}"/></linearGradient>
    <radialGradient id="nebula-a"><stop offset="0" stop-color="{palette['glow_a']}" stop-opacity=".30"/><stop offset="1" stop-color="{palette['glow_a']}" stop-opacity="0"/></radialGradient>
    <radialGradient id="nebula-b"><stop offset="0" stop-color="{palette['glow_b']}" stop-opacity=".22"/><stop offset="1" stop-color="{palette['glow_b']}" stop-opacity="0"/></radialGradient>
    <linearGradient id="beam-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{palette['beam']}" stop-opacity=".34"/><stop offset="1" stop-color="{palette['beam']}" stop-opacity="0"/></linearGradient>
    <filter id="signal-glow" x="-120%" y="-120%" width="340%" height="340%"><feGaussianBlur stdDeviation="4.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="small-glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <clipPath id="constellation-main" clipPathUnits="userSpaceOnUse"><rect class="pass-motion clip-motion" x="{FLARE_MAIN_X:.1f}" y="{CLIP_TOP:.1f}" width="{FLARE_MAIN_WIDTH:.1f}" height="{CLIP_BOTTOM - CLIP_TOP:.1f}" transform="translate({FALLBACK_X:.1f} 0)"/></clipPath>
    <clipPath id="constellation-core" clipPathUnits="userSpaceOnUse"><rect class="pass-motion clip-motion" x="{FLARE_CORE_X:.1f}" y="{CLIP_TOP - 5:.1f}" width="{FLARE_CORE_WIDTH:.1f}" height="{CLIP_BOTTOM - CLIP_TOP + 10:.1f}" transform="translate({FALLBACK_X:.1f} 0)"/></clipPath>
  </defs>
  <style>
    text {{ font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .banner-title {{ font-size:14px;font-weight:760;letter-spacing:2.4px;fill:{palette['text']}; }}
    .banner-meta {{ font-size:12px;font-weight:560;fill:{palette['muted']}; }}
    .pass-motion {{ animation:constellation-pass {CYCLE_DURATION:.1f}s cubic-bezier(.42,.02,.32,1) infinite; }}
    .moving-pass {{ transform:translate({FALLBACK_X:.1f}px,0);opacity:1; }}
    .flare-layer {{ opacity:1; }}
    .twinkle {{ animation:twinkle 4s ease-in-out infinite alternate; }}
    .trail {{ stroke-dasharray:6 12;animation:trail 8s linear infinite; }}
    @keyframes constellation-pass {{
      0%,3% {{ transform:translateX({TRAVEL_START:.1f}px);opacity:0; }}
      7% {{ transform:translateX({TRAVEL_START:.1f}px);opacity:1; }}
      39% {{ transform:translateX({TRAVEL_END:.1f}px);opacity:1; }}
      45%,100% {{ transform:translateX({TRAVEL_END:.1f}px);opacity:0; }}
    }}
    @keyframes twinkle {{ from{{opacity:.12}}to{{opacity:.78}} }}
    @keyframes trail {{ to{{stroke-dashoffset:-260}} }}
    @media (prefers-reduced-motion: reduce) {{
      .pass-motion,.twinkle,.trail {{ animation:none!important; }}
      .moving-pass {{ transform:translate({FALLBACK_X:.1f}px,0);opacity:1; }}
      .clip-motion {{ transform:translate({FALLBACK_X:.1f}px,0); }}
      .flare-layer,.scan-beam {{ display:none; }}
    }}
  </style>
  <rect x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="26" fill="url(#background)" stroke="{palette['edge']}" stroke-width="2"/>
  <circle cx="845" cy="40" r="240" fill="url(#nebula-a)"/><circle cx="300" cy="260" r="220" fill="url(#nebula-b)"/>
  <g>{stars}</g>
  <text x="48" y="39" class="banner-title">CONTRIBUTION CONSTELLATION</text>
  <text x="48" y="62" class="banner-meta">ROLLING 26-WEEK WINDOW · {display.contributions} SIGNALS</text>
  <text x="1052" y="39" text-anchor="end" class="banner-meta">{escape(start_date)} → {escape(end_date)}</text>
  <path d="M58 {ORBIT_Y:.1f}Q500 12 930 {ORBIT_Y:.1f}" fill="none" stroke="{palette['orbit']}" stroke-width="1.4" opacity=".55" stroke-dasharray="4 9"/>
  <g class="lanes">{lanes}</g>
  <g class="signal-matrix">{base_markup}</g>
  <g class="flare-layer" clip-path="url(#constellation-main)">{flare_markup}</g>
  <g class="flare-layer" clip-path="url(#constellation-core)">{core_markup}</g>
  <circle cx="1016" cy="270" r="104" fill="{palette['planet']}" stroke="{palette['planet_edge']}" stroke-width="2"/>
  <path d="M930 260Q1005 222 1098 268" fill="none" stroke="{palette['beam']}" stroke-width="4" opacity=".28"/>
  <g class="moving-pass pass-motion" transform="translate({FALLBACK_X:.1f} 0)">
    <path class="trail" d="M-105 {ORBIT_Y:.1f}H-18" stroke="{palette['trail']}" stroke-width="2.4" opacity=".65"/>
    <path class="scan-beam" d="M-21 {ORBIT_Y + 12:.1f}L-52 {CLIP_BOTTOM:.1f}H52L21 {ORBIT_Y + 12:.1f}Z" fill="url(#beam-gradient)" opacity=".46"/>
    <g transform="translate(0 {ORBIT_Y:.1f})" filter="url(#small-glow)">{render_satellite(palette)}</g>
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

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "contribution-scan.svg").write_text(render_svg(calendar, args.user, "light"), encoding="utf-8")
    (args.output / "contribution-scan-dark.svg").write_text(render_svg(calendar, args.user, "dark"), encoding="utf-8")
    recent = recent_calendar(calendar)
    print(f"Generated contribution constellation for {args.user}: {recent.contributions} signals across {len(recent.weeks)} weeks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
