#!/usr/bin/env python3
"""Generate an animated GitHub contribution constellation as accessible SVG.

The latest 26 contribution weeks become a compact field of stars. Active days
remain visibly brighter even when animation is disabled. During a short CubeSat
pass, the strongest signals expand into luminous four-point flares.
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
HEIGHT = 258
GRID_X0 = 62.0
GRID_X1 = 944.0
GRID_Y0 = 92.0
GRID_ROW_GAP = 20.0
RECENT_WEEK_LIMIT = 26

ORBIT_Y = 58.0
SATELLITE_SCALE = 1.10
CYCLE_DURATION = 20.0
TRAVEL_START = GRID_X0 + 15.0
TRAVEL_END = GRID_X1 - 20.0
FALLBACK_X = GRID_X1 - 62.0

CLIP_TOP = 78.0
CLIP_BOTTOM = 226.0
FLARE_MAIN_X = -49.0
FLARE_MAIN_WIDTH = 98.0
FLARE_CORE_X = -10.0
FLARE_CORE_WIDTH = 20.0


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
        "bg0": "#F7FAFF", "bg1": "#E8F0FF", "edge": "#B8C8E4",
        "text": "#0F172A", "muted": "#5A6A83", "lane": "#B8C7DE",
        "zero": "#B9C7DA",
        "levels": ["#2092AE", "#0788B0", "#2563EB", "#7C3AED"],
        "flare": ["#06B6D4", "#38BDF8", "#6366F1", "#D946EF"],
        "core_mid": "#FFFFFF", "core_high": "#FFF7FF",
        "orbit": "#64748B", "beam": "#0EA5E9", "trail": "#7C3AED",
        "body": "#FFFFFF", "body_edge": "#52617D",
        "solar": "#2563EB", "solar_edge": "#67E8F9",
        "solar_line": "#BAE6FD", "core": "#DB2777",
        "glow_a": "#7C3AED", "glow_b": "#0891B2",
        "star": ["#0891B2", "#2563EB", "#7C3AED", "#DB2777", "#64748B"],
    },
    "dark": {
        "bg0": "#050816", "bg1": "#0B1028", "edge": "#33466F",
        "text": "#F8FAFC", "muted": "#A7B4D0", "lane": "#263554",
        "zero": "#2D3B56",
        "levels": ["#2E91A8", "#22B0CD", "#60A5FA", "#A78BFA"],
        "flare": ["#67E8F9", "#7DD3FC", "#A5B4FC", "#F0ABFC"],
        "core_mid": "#E8FCFF", "core_high": "#FFF4FF",
        "orbit": "#7583A6", "beam": "#22D3EE", "trail": "#A78BFA",
        "body": "#E8EEFF", "body_edge": "#A7B3D1",
        "solar": "#2563EB", "solar_edge": "#67E8F9",
        "solar_line": "#BAE6FD", "core": "#EC4899",
        "glow_a": "#7C3AED", "glow_b": "#22D3EE",
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
    rng = random.Random(20260725)
    end = reference_date or date.today()
    start = end - timedelta(days=365)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    counts: list[int] = []
    for index in range((end - start).days + 1):
        activity = 0.18 + 0.08 * (1 + math.sin(index / 21.0))
        if 0.46 * 365 < index < 0.76 * 365:
            activity += 0.16
        if rng.random() >= activity:
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
    total = sum(day.count for week in selected for day in week)
    return Calendar(contributions=total, weeks=selected, demo=calendar.demo)


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
    return geometry.x0 + week_index * (
        (geometry.x1 - geometry.x0) / (geometry.week_count - 1)
    )


def y_for_weekday(weekday: int, geometry: Geometry) -> float:
    return geometry.y0 + weekday * geometry.row_gap


def circle_path(x: float, y: float, radius: float) -> str:
    return (
        f"M{x - radius:.2f},{y:.2f}"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {2 * radius:.2f},0"
        f"a{radius:.2f},{radius:.2f} 0 1,0 {-2 * radius:.2f},0Z"
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


def build_paths(calendar: Calendar, geometry: Geometry) -> tuple[
    dict[int, str], dict[int, str], dict[str, str]
]:
    max_count = max((day.count for day in flatten_days(calendar)), default=0)
    base_parts: dict[int, list[str]] = {level: [] for level in range(5)}
    flare_parts: dict[int, list[str]] = {level: [] for level in range(1, 5)}
    core_parts: dict[str, list[str]] = {"mid": [], "high": []}

    base_circle = [1.55, 2.30, 3.00]
    for week_index, week in enumerate(calendar.weeks):
        x = x_for_week(week_index, geometry)
        for day in week:
            y = y_for_weekday(day.weekday, geometry)
            level = level_for(day.count, max_count)

            if level <= 2:
                base_parts[level].append(circle_path(x, y, base_circle[level]))
            elif level == 3:
                base_parts[level].append(star_path(x, y, 5.3, 1.65))
            else:
                base_parts[level].append(star_path(x, y, 7.2, 2.05))

            if level == 1:
                flare_parts[level].append(circle_path(x, y, 4.0))
            elif level == 2:
                flare_parts[level].append(star_path(x, y, 6.3, 1.8))
            elif level == 3:
                flare_parts[level].append(star_path(x, y, 9.2, 2.55))
            elif level == 4:
                flare_parts[level].append(star_path(x, y, 12.2, 3.1))

            if level in (2, 3):
                core_parts["mid"].append(circle_path(x, y, 1.45))
            elif level == 4:
                core_parts["high"].append(circle_path(x, y, 2.0))
                core_parts["high"].append(star_path(x, y, 4.2, 1.05))

    return (
        {level: "".join(parts) for level, parts in base_parts.items() if parts},
        {level: "".join(parts) for level, parts in flare_parts.items() if parts},
        {name: "".join(parts) for name, parts in core_parts.items() if parts},
    )


def render_base(paths: dict[int, str], palette: dict[str, object]) -> str:
    opacities = [0.50, 0.82, 0.94, 1.00, 1.00]
    parts: list[str] = []
    for level, path in paths.items():
        color = palette["zero"] if level == 0 else palette["levels"][level - 1]  # type: ignore[index]
        filter_attr = ' filter="url(#small-glow)"' if level >= 3 else ""
        parts.append(
            f'<path data-level="{level}" d="{path}" fill="{color}" '
            f'opacity="{opacities[level]:.2f}"{filter_attr}/>'
        )
    return "".join(parts)


def render_flare(paths: dict[int, str], palette: dict[str, object]) -> str:
    parts: list[str] = []
    for level, path in paths.items():
        parts.append(
            f'<path data-flare-level="{level}" d="{path}" '
            f'fill="{palette["flare"][level - 1]}" filter="url(#signal-glow)"/>'  # type: ignore[index]
        )
    return "".join(parts)


def render_cores(paths: dict[str, str], palette: dict[str, object]) -> str:
    parts: list[str] = []
    if "mid" in paths:
        parts.append(
            f'<path data-flare-core="mid" d="{paths["mid"]}" fill="{palette["core_mid"]}"/>'
        )
    if "high" in paths:
        parts.append(
            f'<path data-flare-core="high" d="{paths["high"]}" fill="{palette["core_high"]}"/>'
        )
    return "".join(parts)


def render_satellite(palette: dict[str, object]) -> str:
    return f'''<g transform="scale({SATELLITE_SCALE:.2f})">
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
    rng = random.Random(9501 if theme == "dark" else 9502)
    colors = palette["star"]  # type: ignore[assignment]
    parts: list[str] = []
    for _ in range(44):
        x = rng.uniform(18, WIDTH - 18)
        y = rng.uniform(18, HEIGHT - 18)
        r = rng.choice([0.55, 0.7, 0.9, 1.15, 1.45])
        parts.append(
            f'<circle class="twinkle" cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" '
            f'fill="{rng.choice(colors)}" opacity="{rng.uniform(.12, .48):.2f}" '
            f'style="animation-duration:{rng.uniform(3.2, 7.0):.2f}s;'
            f'animation-delay:{rng.uniform(-7.0, 0.0):.2f}s"/>'
        )
    return "".join(parts)


def calendar_period(calendar: Calendar) -> tuple[str, str]:
    dates = sorted(day.date for day in flatten_days(calendar))
    return (dates[0], dates[-1]) if dates else ("unknown", "unknown")


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    display = recent_calendar(calendar)
    palette = PALETTES[theme]
    geometry = Geometry(week_count=max(1, len(display.weeks)))
    start_date, end_date = calendar_period(display)
    base_paths, flare_paths, core_paths = build_paths(display, geometry)
    base_markup = render_base(base_paths, palette)
    flare_markup = render_flare(flare_paths, palette)
    core_markup = render_cores(core_paths, palette)
    stars = background_stars(palette, theme)

    lanes = "".join(
        f'<line x1="{geometry.x0 - 9:.1f}" y1="{y_for_weekday(day, geometry):.1f}" '
        f'x2="{geometry.x1 + 9:.1f}" y2="{y_for_weekday(day, geometry):.1f}" '
        f'stroke="{palette["lane"]}" stroke-width=".8" opacity=".27" stroke-dasharray="1 8"/>'
        for day in range(7)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}"
 viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">{escape(login)} contribution constellation, latest {len(display.weeks)} weeks</title>
<desc id="desc">GitHub contribution activity from {escape(start_date)} to {escape(end_date)} rendered as a compact field of stars. A CubeSat crosses the constellation and briefly amplifies active days.</desc>
<defs>
  <linearGradient id="cc-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{palette['bg0']}"/><stop offset="1" stop-color="{palette['bg1']}"/></linearGradient>
  <radialGradient id="cc-nebula-a"><stop offset="0" stop-color="{palette['glow_a']}" stop-opacity=".27"/><stop offset="1" stop-color="{palette['glow_a']}" stop-opacity="0"/></radialGradient>
  <radialGradient id="cc-nebula-b"><stop offset="0" stop-color="{palette['glow_b']}" stop-opacity=".20"/><stop offset="1" stop-color="{palette['glow_b']}" stop-opacity="0"/></radialGradient>
  <linearGradient id="cc-beam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{palette['beam']}" stop-opacity=".42"/><stop offset="1" stop-color="{palette['beam']}" stop-opacity="0"/></linearGradient>
  <filter id="signal-glow" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="4.5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="small-glow" x="-120%" y="-120%" width="340%" height="340%"><feGaussianBlur stdDeviation="1.8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="cc-main" clipPathUnits="userSpaceOnUse"><rect class="pass-motion clip-motion" x="{FLARE_MAIN_X:.1f}" y="{CLIP_TOP:.1f}" width="{FLARE_MAIN_WIDTH:.1f}" height="{CLIP_BOTTOM - CLIP_TOP:.1f}" transform="translate({FALLBACK_X:.1f} 0)"/></clipPath>
  <clipPath id="cc-core" clipPathUnits="userSpaceOnUse"><rect class="pass-motion clip-motion" x="{FLARE_CORE_X:.1f}" y="{CLIP_TOP - 5:.1f}" width="{FLARE_CORE_WIDTH:.1f}" height="{CLIP_BOTTOM - CLIP_TOP + 10:.1f}" transform="translate({FALLBACK_X:.1f} 0)"/></clipPath>
</defs>
<style>
text{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.label{{font-size:12px;font-weight:820;letter-spacing:2.2px;fill:{palette['text']}}}.meta{{font-size:10.8px;font-weight:590;fill:{palette['muted']}}}.pass-motion{{animation:cc-pass {CYCLE_DURATION:.1f}s cubic-bezier(.42,.02,.32,1) infinite}}.moving-pass{{transform:translate({FALLBACK_X:.1f}px,0);opacity:1}}.twinkle{{animation:cc-twinkle 4s ease-in-out infinite alternate}}.trail{{stroke-dasharray:6 12;animation:cc-trail 7s linear infinite}}@keyframes cc-pass{{0%,3%{{transform:translateX({TRAVEL_START:.1f}px);opacity:0}}7%{{transform:translateX({TRAVEL_START:.1f}px);opacity:1}}47%{{transform:translateX({TRAVEL_END:.1f}px);opacity:1}}54%,100%{{transform:translateX({TRAVEL_END:.1f}px);opacity:0}}}}@keyframes cc-twinkle{{from{{opacity:.10}}to{{opacity:.78}}}}@keyframes cc-trail{{to{{stroke-dashoffset:-250}}}}@media(prefers-reduced-motion:reduce){{.pass-motion,.twinkle,.trail{{animation:none!important}}.moving-pass{{transform:translate({FALLBACK_X:.1f}px,0);opacity:1}}.clip-motion{{transform:translate({FALLBACK_X:.1f}px,0)}}.flare-layer,.scan-beam{{display:none}}}}
</style>
<rect x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="25" fill="url(#cc-bg)" stroke="{palette['edge']}" stroke-width="2"/><circle cx="870" cy="8" r="220" fill="url(#cc-nebula-a)"/><circle cx="260" cy="250" r="190" fill="url(#cc-nebula-b)"/><g>{stars}</g><text x="38" y="31" class="label">LIVE CONTRIBUTION TELEMETRY</text><text x="38" y="50" class="meta">26-WEEK SIGNAL MAP · {display.contributions} CONTRIBUTIONS</text><text x="1062" y="31" text-anchor="end" class="meta">{escape(start_date)} → {escape(end_date)}</text><path d="M48 {ORBIT_Y:.1f}Q520 8 1020 {ORBIT_Y:.1f}" fill="none" stroke="{palette['orbit']}" stroke-width="1.4" opacity=".58" stroke-dasharray="4 9"/><g>{lanes}</g><g class="signal-matrix">{base_markup}</g><g class="flare-layer" clip-path="url(#cc-main)">{flare_markup}</g><g class="flare-layer" clip-path="url(#cc-core)">{core_markup}</g><g class="moving-pass pass-motion" transform="translate({FALLBACK_X:.1f} 0)"><path class="trail" d="M-118 {ORBIT_Y:.1f}H-22" stroke="{palette['trail']}" stroke-width="2.5" opacity=".72"/><path class="scan-beam" d="M-24 {ORBIT_Y + 13:.1f}L-58 {CLIP_BOTTOM:.1f}H58L24 {ORBIT_Y + 13:.1f}Z" fill="url(#cc-beam)" opacity=".55"/><g transform="translate(0 {ORBIT_Y:.1f})" filter="url(#small-glow)">{render_satellite(palette)}</g></g></svg>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("GITHUB_USER", "DavCalo"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--demo", action="store_true")
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
    print(f"Generated contribution constellation for {args.user}: {recent.contributions} contributions across {len(recent.weeks)} weeks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
