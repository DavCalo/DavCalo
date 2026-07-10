#!/usr/bin/env python3
"""Generate an animated GitHub contribution flight map as SVG.

Each day is rendered as a signal in a contribution grid. A CubeSat follows a
closed, deterministic flight path whose altitude is derived from the smoothed
weekly contribution intensity. The SVG is generated in light and dark themes.

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
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Sequence

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

WIDTH = 1000
HEIGHT = 342
GRID_X0 = 150.0
GRID_X1 = 900.0
GRID_Y0 = 112.0
GRID_ROW_GAP = 19.5
ROUTE_MIN_Y = 102.0
ROUTE_MAX_Y = 210.0
RETURN_Y = 270.0


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


PALETTES = {
    "light": {
        "background": "#F8FAFC",
        "panel": "#FFFFFF",
        "panel_2": "#F1F5F9",
        "border": "#D8E4EE",
        "text": "#0F172A",
        "muted": "#64748B",
        "grid": "#CBD5E1",
        "zero": "#DDE7EF",
        "levels": ["#BAE6FD", "#7DD3FC", "#38BDF8", "#0284C7"],
        "orbit": "#0284C7",
        "orbit_soft": "#7DD3FC",
        "accent": "#7C3AED",
        "body": "#334155",
        "body_edge": "#0F172A",
        "solar": "#0891B2",
        "solar_grid": "#CFFAFE",
        "good": "#059669",
    },
    "dark": {
        "background": "#060D18",
        "panel": "#0A1728",
        "panel_2": "#0D2035",
        "border": "#1D3952",
        "text": "#E6F3FF",
        "muted": "#8FA6BC",
        "grid": "#183249",
        "zero": "#183047",
        "levels": ["#164E63", "#0E7490", "#22D3EE", "#A5F3FC"],
        "orbit": "#38BDF8",
        "orbit_soft": "#164E63",
        "accent": "#A78BFA",
        "body": "#DDEAF4",
        "body_edge": "#BAE6FD",
        "solar": "#0E7490",
        "solar_grid": "#A5F3FC",
        "good": "#34D399",
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
            "User-Agent": "contribution-flight-generator",
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


def demo_calendar() -> Calendar:
    rng = random.Random(1207)
    start = date.today() - timedelta(days=370)
    counts: list[int] = []
    for index in range(371):
        seasonal = 0.16 + 0.08 * (1 + math.sin(index / 21.0))
        if rng.random() >= seasonal:
            counts.append(0)
            continue
        amount = 1 + int(rng.expovariate(0.35))
        if rng.random() < 0.08:
            amount += rng.randint(7, 18)
        counts.append(min(amount, 34))

    weeks: list[list[Day]] = []
    for week_index in range(53):
        week: list[Day] = []
        for weekday in range(7):
            idx = week_index * 7 + weekday
            if idx >= len(counts):
                break
            current = start + timedelta(days=idx)
            week.append(Day(current.isoformat(), weekday, counts[idx]))
        weeks.append(week)
    return Calendar(total=sum(counts), weeks=weeks, demo=True)


def flatten_days(calendar: Calendar) -> list[Day]:
    return [day for week in calendar.weeks for day in week]


def longest_streak(days: Sequence[Day]) -> int:
    best = current = 0
    for item in sorted(days, key=lambda day: day.date):
        if item.count > 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def level_for(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = math.log1p(count) / math.log1p(max_count)
    return min(4, max(1, math.ceil(ratio * 4)))


def x_for_week(week_index: int, week_count: int) -> float:
    if week_count <= 1:
        return (GRID_X0 + GRID_X1) / 2
    return GRID_X0 + week_index * ((GRID_X1 - GRID_X0) / (week_count - 1))


def y_for_weekday(weekday: int) -> float:
    return GRID_Y0 + weekday * GRID_ROW_GAP


def weekly_totals(calendar: Calendar) -> list[int]:
    return [sum(day.count for day in week) for week in calendar.weeks]


def smooth(values: Sequence[float], passes: int = 2) -> list[float]:
    result = list(values)
    if len(result) < 3:
        return result
    for _ in range(passes):
        source = result
        result = []
        for i in range(len(source)):
            left = source[max(0, i - 1)]
            center = source[i]
            right = source[min(len(source) - 1, i + 1)]
            result.append((left + 2 * center + right) / 4)
    return result


def activity_route_points(calendar: Calendar) -> list[tuple[float, float]]:
    totals = weekly_totals(calendar)
    max_total = max(totals, default=0)
    if max_total <= 0:
        intensities = [0.0 for _ in totals]
    else:
        denominator = math.log1p(max_total)
        intensities = [math.log1p(value) / denominator for value in totals]
    intensities = smooth(intensities, passes=3)

    points: list[tuple[float, float]] = []
    for index, intensity in enumerate(intensities):
        x = x_for_week(index, len(totals))
        y = ROUTE_MAX_Y - intensity * (ROUTE_MAX_Y - ROUTE_MIN_Y)
        y = min(ROUTE_MAX_Y, max(ROUTE_MIN_Y, y))
        points.append((x, y))
    return points


def open_catmull_rom(points: Sequence[tuple[float, float]]) -> str:
    if not points:
        return "M 0 0"
    if len(points) == 1:
        return f"M {points[0][0]:.2f} {points[0][1]:.2f}"
    if len(points) == 2:
        return f"M {points[0][0]:.2f} {points[0][1]:.2f} L {points[1][0]:.2f} {points[1][1]:.2f}"

    parts = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    extended = [points[0], *points, points[-1]]
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c1y = min(ROUTE_MAX_Y, max(ROUTE_MIN_Y, c1y))
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        c2y = min(ROUTE_MAX_Y, max(ROUTE_MIN_Y, c2y))
        parts.append(f"C {c1x:.2f} {c1y:.2f}, {c2x:.2f} {c2y:.2f}, {p2[0]:.2f} {p2[1]:.2f}")
    return " ".join(parts)


def build_closed_path(points: Sequence[tuple[float, float]], offset_x: float = 0.0, offset_y: float = 0.0) -> str:
    shifted = [(x - offset_x, y - offset_y) for x, y in points]
    upper = open_catmull_rom(shifted)
    if not points:
        return upper
    start_x, start_y = points[0]
    _, end_y = points[-1]
    return (
        upper
        + f" C {928.0 - offset_x:.2f} {end_y + 10.0 - offset_y:.2f}, "
          f"{930.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}, "
          f"{850.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}"
        + f" C {650.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}, "
          f"{350.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}, "
          f"{150.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}"
        + f" C {72.0 - offset_x:.2f} {RETURN_Y - offset_y:.2f}, "
          f"{72.0 - offset_x:.2f} {start_y + 18.0 - offset_y:.2f}, "
          f"{start_x - offset_x:.2f} {start_y - offset_y:.2f} Z"
    )


def flight_paths(calendar: Calendar) -> tuple[str, str, str, float, float]:
    points = activity_route_points(calendar)
    upper = open_catmull_rom(points)
    if not points:
        return upper, upper, upper, 0.0, 0.0
    start_x, start_y = points[0]
    absolute = build_closed_path(points)
    relative = build_closed_path(points, start_x, start_y)
    return upper, absolute, relative, start_x, start_y


def month_labels(calendar: Calendar) -> list[tuple[float, str]]:
    labels: list[tuple[float, str]] = []
    last_month: int | None = None
    for week_index, week in enumerate(calendar.weeks):
        if not week:
            continue
        first = datetime.fromisoformat(week[0].date)
        if first.month != last_month:
            labels.append((x_for_week(week_index, len(calendar.weeks)), first.strftime("%b").upper()))
            last_month = first.month
    return labels


def render_signal(x: float, y: float, day: Day, level: int, palette: dict[str, object], pulse: bool, delay: float) -> str:
    if level == 0:
        return (
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.75" fill="{palette["zero"]}" opacity="0.86">'
            f'<title>{escape(day.date)}: 0 contributions</title></circle>'
        )
    radius = [0.0, 2.45, 3.05, 3.75, 4.55][level]
    color = palette["levels"][level - 1]  # type: ignore[index]
    animation = ""
    if pulse:
        animation = (
            f'<animate attributeName="r" values="{radius:.2f};{radius + 1.1:.2f};{radius:.2f}" '
            f'dur="2.7s" begin="{delay:.2f}s" repeatCount="indefinite" />'
            f'<animate attributeName="opacity" values="0.72;1;0.72" dur="2.7s" '
            f'begin="{delay:.2f}s" repeatCount="indefinite" />'
        )
    label = "contribution" if day.count == 1 else "contributions"
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" '
        f'filter="url(#signalGlow)">{animation}<title>{escape(day.date)}: {day.count} {label}</title></circle>'
    )


def render_satellite(palette: dict[str, object], motion_path: str, start_x: float, start_y: float) -> str:
    return f'''
      <g transform="translate({start_x:.2f} {start_y:.2f})">
        <g class="satellite" filter="url(#satGlow)">
          <animateMotion path="{motion_path}" dur="19s" repeatCount="indefinite" rotate="auto"/>
          <g transform="scale(0.64)">
          <path d="M -35 0 L -23 0 M 23 0 L 35 0" stroke="{palette['body_edge']}" stroke-width="2.4" stroke-linecap="round"/>
          <rect x="-55" y="-10" width="20" height="20" rx="2.5" fill="{palette['solar']}" stroke="{palette['solar_grid']}" stroke-width="1.2"/>
          <path d="M -48 -10 V 10 M -41 -10 V 10 M -55 0 H -35" stroke="{palette['solar_grid']}" stroke-width="0.8" opacity="0.72"/>
          <rect x="35" y="-10" width="20" height="20" rx="2.5" fill="{palette['solar']}" stroke="{palette['solar_grid']}" stroke-width="1.2"/>
          <path d="M 42 -10 V 10 M 49 -10 V 10 M 35 0 H 55" stroke="{palette['solar_grid']}" stroke-width="0.8" opacity="0.72"/>
          <rect x="-23" y="-15" width="46" height="30" rx="7" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.7"/>
          <rect x="-11" y="-7" width="22" height="14" rx="3" fill="{palette['panel_2']}" stroke="{palette['orbit']}" stroke-width="1.3"/>
          <circle cx="0" cy="0" r="3.8" fill="{palette['orbit']}">
            <animate attributeName="opacity" values="0.45;1;0.45" dur="1.4s" repeatCount="indefinite"/>
          </circle>
          <path d="M 0 -15 V -27" stroke="{palette['body_edge']}" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="0" cy="-28" r="2.4" fill="{palette['orbit']}"/>
          <path d="M 5 -30 Q 13 -36 18 -28" fill="none" stroke="{palette['orbit']}" stroke-width="1.6" stroke-linecap="round">
            <animate attributeName="opacity" values="0.15;0.95;0.15" dur="1.25s" repeatCount="indefinite"/>
          </path>
          <path d="M -26 0 H -40" stroke="{palette['orbit']}" stroke-width="2" stroke-linecap="round" opacity="0.7">
            <animate attributeName="stroke-dasharray" values="2 12;8 6;2 12" dur="1.1s" repeatCount="indefinite"/>
          </path>
          </g>
        </g>
      </g>'''


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    palette = PALETTES[theme]
    days = flatten_days(calendar)
    max_count = max((day.count for day in days), default=0)
    active_days = sum(day.count > 0 for day in days)
    best_streak = longest_streak(days)
    upper_path, closed_path, motion_path, start_x, start_y = flight_paths(calendar)

    active_counts = sorted((day.count for day in days if day.count > 0), reverse=True)
    threshold = active_counts[min(9, len(active_counts) - 1)] if active_counts else 10**9

    signals: list[str] = []
    for week_index, week in enumerate(calendar.weeks):
        for day in week:
            x = x_for_week(week_index, len(calendar.weeks))
            y = y_for_weekday(day.weekday)
            level = level_for(day.count, max_count)
            pulse = day.count >= threshold and day.count > 0
            delay = ((week_index * 3 + day.weekday) % 13) * 0.17
            signals.append(render_signal(x, y, day, level, palette, pulse, delay))

    months = "".join(
        f'<text x="{x:.2f}" y="93" fill="{palette["muted"]}" font-size="9.5" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">{label}</text>'
        for x, label in month_labels(calendar)
        if x <= GRID_X1 - 15
    )
    suffix = "DEMO SIGNAL" if calendar.demo else "LIVE FROM GITHUB"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(login)} animated GitHub contribution flight</title>
  <desc id="desc">Daily GitHub contributions are shown as a signal grid. The CubeSat follows a smooth closed route whose altitude is derived from weekly activity.</desc>
  <defs>
    <linearGradient id="panelFill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{palette['panel']}"/>
      <stop offset="1" stop-color="{palette['background']}"/>
    </linearGradient>
    <linearGradient id="routeGradient" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{palette['orbit']}" stop-opacity="0.18"/>
      <stop offset="0.48" stop-color="{palette['orbit']}" stop-opacity="0.95"/>
      <stop offset="1" stop-color="{palette['accent']}" stop-opacity="0.35"/>
    </linearGradient>
    <filter id="signalGlow" x="-180%" y="-180%" width="460%" height="460%">
      <feGaussianBlur stdDeviation="2.1" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="satGlow" x="-130%" y="-130%" width="360%" height="360%">
      <feGaussianBlur stdDeviation="3.3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="panelClip"><rect x="1" y="1" width="998" height="340" rx="24"/></clipPath>
  </defs>

  <rect x="1" y="1" width="998" height="340" rx="24" fill="url(#panelFill)" stroke="{palette['border']}" stroke-width="2"/>

  <g clip-path="url(#panelClip)">
    <circle cx="924" cy="20" r="155" fill="{palette['orbit']}" opacity="0.035"/>
    <circle cx="48" cy="344" r="142" fill="{palette['accent']}" opacity="0.035"/>

    <g transform="translate(34 26)">
      <rect width="12" height="12" rx="3" fill="{palette['orbit']}" opacity="0.95"/>
      <circle cx="6" cy="6" r="2.2" fill="{palette['panel']}"/>
      <text x="22" y="11" fill="{palette['text']}" font-size="16" font-weight="700" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1.15">{escape(login.upper())} // CONTRIBUTION ORBIT</text>
      <text x="22" y="29" fill="{palette['muted']}" font-size="10.5" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1">{suffix} · STABLE ORBIT · ALTITUDE = WEEKLY ACTIVITY</text>
    </g>

    <g transform="translate(680 20)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
      <rect x="0" y="0" width="92" height="44" rx="10" fill="{palette['panel_2']}" stroke="{palette['border']}"/>
      <text x="46" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.5" letter-spacing="1">CONTRIBUTIONS</text>
      <text x="46" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{calendar.total}</text>
      <rect x="101" y="0" width="92" height="44" rx="10" fill="{palette['panel_2']}" stroke="{palette['border']}"/>
      <text x="147" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.5" letter-spacing="1">ACTIVE DAYS</text>
      <text x="147" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{active_days}</text>
      <rect x="202" y="0" width="92" height="44" rx="10" fill="{palette['panel_2']}" stroke="{palette['border']}"/>
      <text x="248" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.5" letter-spacing="1">BEST STREAK</text>
      <text x="248" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{best_streak}d</text>
    </g>

    {months}
    <g fill="{palette['muted']}" font-size="9.5" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" text-anchor="end">
      <text x="98" y="116">SUN</text>
      <text x="98" y="155">TUE</text>
      <text x="98" y="194">THU</text>
      <text x="98" y="233">SAT</text>
    </g>

    <g opacity="0.5">
      <line x1="{GRID_X0}" y1="{GRID_Y0}" x2="{GRID_X1}" y2="{GRID_Y0}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
      <line x1="{GRID_X0}" y1="{GRID_Y0 + 3 * GRID_ROW_GAP}" x2="{GRID_X1}" y2="{GRID_Y0 + 3 * GRID_ROW_GAP}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
      <line x1="{GRID_X0}" y1="{GRID_Y0 + 6 * GRID_ROW_GAP}" x2="{GRID_X1}" y2="{GRID_Y0 + 6 * GRID_ROW_GAP}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
    </g>

    <path id="activityPath" d="{upper_path}" fill="none" stroke="url(#routeGradient)" stroke-width="2.1" stroke-linecap="round" opacity="0.9"/>
    <path id="closedFlightPath" d="{closed_path}" fill="none" stroke="{palette['orbit_soft']}" stroke-width="1.15" stroke-dasharray="3 8" stroke-linecap="round" opacity="0.5">
      <animate attributeName="stroke-dashoffset" from="0" to="-44" dur="2.4s" repeatCount="indefinite"/>
    </path>

    <g aria-label="Contribution signals">{''.join(signals)}</g>

    {render_satellite(palette, motion_path, start_x, start_y)}

    <g transform="translate(34 307)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="9.5" fill="{palette['muted']}">
      <circle cx="4" cy="0" r="1.75" fill="{palette['zero']}"/>
      <circle cx="23" cy="0" r="2.45" fill="{palette['levels'][0]}"/>
      <circle cx="44" cy="0" r="3.05" fill="{palette['levels'][1]}"/>
      <circle cx="67" cy="0" r="3.75" fill="{palette['levels'][2]}"/>
      <circle cx="93" cy="0" r="4.55" fill="{palette['levels'][3]}" filter="url(#signalGlow)"/>
      <text x="110" y="4">signal strength</text>
    </g>

    <g transform="translate(702 301)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
      <circle cx="0" cy="4" r="3" fill="{palette['good']}">
        <animate attributeName="opacity" values="0.45;1;0.45" dur="1.4s" repeatCount="indefinite"/>
      </circle>
      <text x="12" y="8" fill="{palette['muted']}" font-size="9.5" letter-spacing="1.05">ORBIT STABLE · BUILD · LEARN · LAUNCH</text>
    </g>
  </g>
</svg>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("GITHUB_USER", "DavCalo"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--demo", action="store_true", help="Generate deterministic preview data without calling GitHub")
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
    (args.output / "contribution-orbit.svg").write_text(render_svg(calendar, args.user, "light"), encoding="utf-8")
    (args.output / "contribution-orbit-dark.svg").write_text(render_svg(calendar, args.user, "dark"), encoding="utf-8")
    print(f"Generated contribution orbit for {args.user}: {calendar.total} contributions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
