#!/usr/bin/env python3
"""Generate an animated GitHub contribution constellation as SVG.

The contribution calendar is fetched from GitHub's GraphQL API. Each day is
rendered as a star, while a small CubeSat follows a path derived from the most
active part of every week.

The script only uses Python's standard library.
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
from typing import Iterable, Sequence

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
        "panel_border": "#DCE8F3",
        "text": "#0F172A",
        "muted": "#64748B",
        "orbit": "#0EA5E9",
        "orbit_faint": "#7DD3FC",
        "zero": "#DCE7F0",
        "levels": ["#BAE6FD", "#7DD3FC", "#38BDF8", "#0284C7"],
        "sat_body": "#334155",
        "sat_edge": "#0F172A",
        "sat_panel": "#0891B2",
        "sat_panel_grid": "#A5F3FC",
        "accent": "#7C3AED",
        "glow": "#38BDF8",
    },
    "dark": {
        "background": "#07111F",
        "panel": "#0B192C",
        "panel_border": "#1E3A56",
        "text": "#E6F3FF",
        "muted": "#94A3B8",
        "orbit": "#38BDF8",
        "orbit_faint": "#164E63",
        "zero": "#1A2C3E",
        "levels": ["#164E63", "#0E7490", "#22D3EE", "#67E8F9"],
        "sat_body": "#E2E8F0",
        "sat_edge": "#BAE6FD",
        "sat_panel": "#0E7490",
        "sat_panel_grid": "#A5F3FC",
        "accent": "#A78BFA",
        "glow": "#67E8F9",
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
            "X-Github-Next-Global-ID": "1",
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

    raw_calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks: list[list[Day]] = []
    for raw_week in raw_calendar["weeks"]:
        week = [
            Day(
                date=raw_day["date"],
                weekday=int(raw_day["weekday"]),
                count=int(raw_day["contributionCount"]),
            )
            for raw_day in raw_week["contributionDays"]
        ]
        weeks.append(week)

    return Calendar(total=int(raw_calendar["totalContributions"]), weeks=weeks)


def demo_calendar() -> Calendar:
    """Create deterministic data for the local preview only."""
    rng = random.Random(1207)
    start = date.today() - timedelta(days=370)
    raw_counts: list[int] = []

    for index in range(371):
        wave = 0.14 + 0.12 * (1 + math.sin(index / 19.0))
        active = rng.random() < wave
        if not active:
            raw_counts.append(0)
            continue
        count = 1 + int(rng.expovariate(0.32))
        if rng.random() < 0.06:
            count += rng.randint(8, 20)
        raw_counts.append(min(count, 38))

    weeks: list[list[Day]] = []
    for week_index in range(53):
        week: list[Day] = []
        for weekday in range(7):
            idx = week_index * 7 + weekday
            if idx >= len(raw_counts):
                break
            current = start + timedelta(days=idx)
            week.append(Day(current.isoformat(), weekday, raw_counts[idx]))
        weeks.append(week)

    return Calendar(total=sum(raw_counts), weeks=weeks, demo=True)


def flatten_days(calendar: Calendar) -> list[Day]:
    return [day for week in calendar.weeks for day in week]


def longest_streak(days: Sequence[Day]) -> int:
    best = current = 0
    for day in sorted(days, key=lambda item: item.date):
        if day.count > 0:
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


def point_for(week_index: int, weekday: int, week_count: int) -> tuple[float, float]:
    x = 88 + week_index * (760 / max(1, week_count - 1))
    wave = math.sin(week_index * 0.42) * 6.5 + math.sin(week_index * 0.15) * 4
    y = 104 + weekday * 21 + wave
    return x, y


def route_points(calendar: Calendar) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    previous_weekday = 3.0
    week_count = len(calendar.weeks)

    for index, week in enumerate(calendar.weeks):
        weight = sum(day.count for day in week)
        if weight:
            weighted_day = sum(day.weekday * day.count for day in week) / weight
            previous_weekday = weighted_day
        else:
            weighted_day = previous_weekday + math.sin(index * 0.7) * 0.18
        x, y = point_for(index, int(round(weighted_day)), week_count)
        # Keep the weighted position rather than snapping fully to one row.
        _, y0 = point_for(index, 0, week_count)
        y = y0 + weighted_day * 21
        points.append((x, y))

    return points


def catmull_rom_path(points: Sequence[tuple[float, float]]) -> str:
    if not points:
        return "M 0 0"
    if len(points) < 3:
        return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)

    parts = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    extended = [points[0], *points, points[-1]]
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        parts.append(
            f"C {c1[0]:.2f} {c1[1]:.2f}, {c2[0]:.2f} {c2[1]:.2f}, {p2[0]:.2f} {p2[1]:.2f}"
        )
    return " ".join(parts)


def render_star(x: float, y: float, level: int, color: str, pulse_delay: float | None) -> str:
    if level == 0:
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.55" fill="{color}" />'

    radius = [0, 2.3, 2.9, 3.6, 4.4][level]
    animation = ""
    if pulse_delay is not None:
        animation = (
            f'<animate attributeName="opacity" values="0.62;1;0.62" dur="2.8s" '
            f'begin="{pulse_delay:.2f}s" repeatCount="indefinite" />'
        )
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" '
        f'filter="url(#starGlow)">{animation}</circle>'
    )


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    palette = PALETTES[theme]
    days = flatten_days(calendar)
    max_count = max((day.count for day in days), default=0)
    active_days = sum(day.count > 0 for day in days)
    best_streak = longest_streak(days)
    week_count = len(calendar.weeks)
    route = catmull_rom_path(route_points(calendar))

    stars: list[str] = []
    active_sorted = sorted((day.count for day in days if day.count > 0), reverse=True)
    pulse_threshold = active_sorted[min(11, len(active_sorted) - 1)] if active_sorted else 10**9

    for week_index, week in enumerate(calendar.weeks):
        for day in week:
            x, y = point_for(week_index, day.weekday, week_count)
            level = level_for(day.count, max_count)
            color = palette["zero"] if level == 0 else palette["levels"][level - 1]
            delay = ((week_index + day.weekday) % 9) * 0.23 if day.count >= pulse_threshold and day.count > 0 else None
            stars.append(render_star(x, y, level, color, delay))

    suffix = " // demo data" if calendar.demo else " // last 365 days"
    title = f"{login.upper()} // CONTRIBUTION ORBIT"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="960" height="286" viewBox="0 0 960 286" role="img" aria-labelledby="title desc">
  <title id="title">{escape(login)} animated GitHub contribution orbit</title>
  <desc id="desc">Each star represents a day of GitHub activity. A CubeSat follows a route weighted by the activity of each week.</desc>
  <defs>
    <filter id="starGlow" x="-180%" y="-180%" width="460%" height="460%">
      <feGaussianBlur stdDeviation="2.2" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="satGlow" x="-120%" y="-120%" width="340%" height="340%">
      <feGaussianBlur stdDeviation="3.2" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="panelFill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{palette['panel']}"/>
      <stop offset="1" stop-color="{palette['background']}"/>
    </linearGradient>
    <clipPath id="panelClip"><rect x="1" y="1" width="958" height="284" rx="22"/></clipPath>
  </defs>

  <rect x="1" y="1" width="958" height="284" rx="22" fill="url(#panelFill)" stroke="{palette['panel_border']}" stroke-width="2"/>

  <g clip-path="url(#panelClip)">
    <circle cx="890" cy="40" r="142" fill="{palette['orbit']}" opacity="0.035"/>
    <circle cx="78" cy="292" r="130" fill="{palette['accent']}" opacity="0.035"/>

    <text x="42" y="42" fill="{palette['text']}" font-size="16" font-weight="700" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1.3">{escape(title)}</text>
    <text x="42" y="64" fill="{palette['muted']}" font-size="11" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1">EACH STAR IS A DAY{escape(suffix.upper())}</text>

    <g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" text-anchor="end">
      <text x="918" y="37" fill="{palette['text']}" font-size="15" font-weight="700">{calendar.total} contributions</text>
      <text x="918" y="58" fill="{palette['muted']}" font-size="11">{active_days} active days · {best_streak} day best streak</text>
    </g>

    <path id="flightPath" d="{route}" fill="none" stroke="{palette['orbit_faint']}" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="3 8" opacity="0.78">
      <animate attributeName="stroke-dashoffset" from="0" to="-44" dur="2.2s" repeatCount="indefinite"/>
    </path>

    <g aria-label="Contribution stars">
      {''.join(stars)}
    </g>

    <g filter="url(#satGlow)" transform="translate(88 165)">
      <animateMotion dur="13s" repeatCount="indefinite" rotate="auto" keyTimes="0;1" keySplines="0.42 0 0.58 1" calcMode="spline">
        <mpath xlink:href="#flightPath"/>
      </animateMotion>

      <g transform="scale(0.82)">
        <line x1="-22" y1="0" x2="-13" y2="0" stroke="{palette['sat_edge']}" stroke-width="2"/>
        <line x1="13" y1="0" x2="22" y2="0" stroke="{palette['sat_edge']}" stroke-width="2"/>
        <rect x="-46" y="-9" width="24" height="18" rx="2" fill="{palette['sat_panel']}" stroke="{palette['sat_panel_grid']}" stroke-width="1"/>
        <line x1="-38" y1="-9" x2="-38" y2="9" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <line x1="-30" y1="-9" x2="-30" y2="9" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <line x1="-46" y1="0" x2="-22" y2="0" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <rect x="22" y="-9" width="24" height="18" rx="2" fill="{palette['sat_panel']}" stroke="{palette['sat_panel_grid']}" stroke-width="1"/>
        <line x1="30" y1="-9" x2="30" y2="9" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <line x1="38" y1="-9" x2="38" y2="9" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <line x1="22" y1="0" x2="46" y2="0" stroke="{palette['sat_panel_grid']}" stroke-width="0.8" opacity="0.7"/>
        <rect x="-13" y="-12" width="26" height="24" rx="4" fill="{palette['sat_body']}" stroke="{palette['sat_edge']}" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="4.2" fill="{palette['orbit']}"/>
        <line x1="0" y1="-12" x2="0" y2="-22" stroke="{palette['sat_edge']}" stroke-width="1.6"/>
        <circle cx="0" cy="-23" r="2.2" fill="{palette['glow']}"/>
        <path d="M 4 -24 Q 12 -29 16 -22" fill="none" stroke="{palette['glow']}" stroke-width="1.5" opacity="0.9">
          <animate attributeName="opacity" values="0.15;1;0.15" dur="1.35s" repeatCount="indefinite"/>
        </path>
        <path d="M 6 -28 Q 18 -36 24 -23" fill="none" stroke="{palette['glow']}" stroke-width="1.2" opacity="0.6">
          <animate attributeName="opacity" values="0.05;0.75;0.05" dur="1.35s" begin="0.18s" repeatCount="indefinite"/>
        </path>
      </g>
    </g>

    <g transform="translate(42 256)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="10" fill="{palette['muted']}">
      <text x="0" y="4">less signal</text>
      <circle cx="76" cy="0" r="1.6" fill="{palette['zero']}"/>
      <circle cx="91" cy="0" r="2.3" fill="{palette['levels'][0]}"/>
      <circle cx="108" cy="0" r="2.9" fill="{palette['levels'][1]}"/>
      <circle cx="127" cy="0" r="3.6" fill="{palette['levels'][2]}"/>
      <circle cx="148" cy="0" r="4.4" fill="{palette['levels'][3]}" filter="url(#starGlow)"/>
      <text x="160" y="4">more signal</text>
    </g>

    <text x="918" y="260" text-anchor="end" fill="{palette['muted']}" font-size="10" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1.2">BUILD · LEARN · LAUNCH</text>
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
    light = render_svg(calendar, args.user, "light")
    dark = render_svg(calendar, args.user, "dark")

    (args.output / "contribution-orbit.svg").write_text(light, encoding="utf-8")
    (args.output / "contribution-orbit-dark.svg").write_text(dark, encoding="utf-8")

    print(
        f"Generated contribution orbit for {args.user}: "
        f"{calendar.total} contributions across {sum(day.count > 0 for day in flatten_days(calendar))} active days"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
