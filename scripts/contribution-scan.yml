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
HEIGHT = 350
GRID_X0 = 132.0
GRID_X1 = 918.0
GRID_Y0 = 132.0
GRID_ROW_GAP = 19.0
SATELLITE_Y = 91.0
SCAN_DURATION = 15.0


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
        "panel_alt": "#F1F5F9",
        "border": "#D9E4EE",
        "text": "#0F172A",
        "muted": "#64748B",
        "grid": "#D5E0E9",
        "zero": "#DCE6EE",
        "levels": ["#BAE6FD", "#67E8F9", "#0EA5E9", "#2563EB"],
        "orbit": "#0284C7",
        "beam": "#38BDF8",
        "accent": "#7C3AED",
        "body": "#E2E8F0",
        "body_edge": "#334155",
        "solar": "#0891B2",
        "solar_grid": "#CFFAFE",
        "good": "#059669",
    },
    "dark": {
        "background": "#07111E",
        "panel": "#0A1728",
        "panel_alt": "#0D2035",
        "border": "#1C3850",
        "text": "#E6F3FF",
        "muted": "#8FA6BC",
        "grid": "#173047",
        "zero": "#183047",
        "levels": ["#164E63", "#0E7490", "#22D3EE", "#A5F3FC"],
        "orbit": "#38BDF8",
        "beam": "#22D3EE",
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


def demo_calendar() -> Calendar:
    rng = random.Random(20260710)
    start = date.today() - timedelta(days=370)
    counts: list[int] = []
    for index in range(371):
        # Deterministic preview with quiet and active phases.
        phase = 0.13 + 0.07 * (1 + math.sin(index / 25.0))
        burst = 0.12 if 145 < index < 230 else 0.0
        if rng.random() >= phase + burst:
            counts.append(0)
            continue
        amount = 1 + int(rng.expovariate(0.42))
        if rng.random() < 0.07:
            amount += rng.randint(6, 16)
        counts.append(min(amount, 30))

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


def scan_delay(week_index: int, week_count: int) -> float:
    if week_count <= 1:
        return 0.0
    # Satellite is visible during the middle 90% of the cycle.
    return 0.04 * SCAN_DURATION + (week_index / (week_count - 1)) * 0.88 * SCAN_DURATION


def render_signal(
    x: float,
    y: float,
    day: Day,
    level: int,
    palette: dict[str, object],
    delay: float,
) -> str:
    if level == 0:
        radius = 1.75
        color = str(palette["zero"])
        base_opacity = 0.82
        glow = ""
    else:
        radius = [0.0, 2.35, 2.95, 3.65, 4.45][level]
        color = str(palette["levels"][level - 1])  # type: ignore[index]
        base_opacity = [0.0, 0.78, 0.84, 0.92, 1.0][level]
        glow = ' filter="url(#signalGlow)"' if level >= 3 else ""

    pulse_radius = radius + (0.75 if level == 0 else 1.25)
    label = "contribution" if day.count == 1 else "contributions"
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" '
        f'opacity="{base_opacity:.2f}"{glow}>'
        f'<animate attributeName="opacity" values="{base_opacity:.2f};1;{base_opacity:.2f};{base_opacity:.2f}" '
        f'keyTimes="0;0.025;0.075;1" begin="{delay:.3f}s" dur="{SCAN_DURATION:.1f}s" repeatCount="indefinite"/>'
        f'<animate attributeName="r" values="{radius:.2f};{pulse_radius:.2f};{radius:.2f};{radius:.2f}" '
        f'keyTimes="0;0.025;0.075;1" begin="{delay:.3f}s" dur="{SCAN_DURATION:.1f}s" repeatCount="indefinite"/>'
        f'<title>{escape(day.date)}: {day.count} {label}</title>'
        f'</circle>'
    )


def render_week_scan(x: float, palette: dict[str, object], delay: float) -> str:
    return (
        f'<line x1="{x:.2f}" y1="{GRID_Y0 - 9:.2f}" x2="{x:.2f}" y2="{GRID_Y0 + 6 * GRID_ROW_GAP + 9:.2f}" '
        f'stroke="{palette["beam"]}" stroke-width="1.2" opacity="0">'
        f'<animate attributeName="opacity" values="0;0.34;0;0" keyTimes="0;0.025;0.075;1" '
        f'begin="{delay:.3f}s" dur="{SCAN_DURATION:.1f}s" repeatCount="indefinite"/>'
        f'</line>'
    )


def render_satellite(palette: dict[str, object]) -> str:
    travel_start = GRID_X0
    travel_end = GRID_X1
    return f'''
    <g class="orbital-scanner" transform="translate(132.00 91.00)" opacity="1">
      <animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.035;0.925;0.965;1" dur="{SCAN_DURATION:.1f}s" repeatCount="indefinite"/>
      <animateTransform attributeName="transform" type="translate"
        values="{travel_start:.2f} {SATELLITE_Y:.2f};{travel_start:.2f} {SATELLITE_Y:.2f};{travel_end:.2f} {SATELLITE_Y:.2f};{travel_end:.2f} {SATELLITE_Y:.2f}"
        keyTimes="0;0.04;0.92;1" dur="{SCAN_DURATION:.1f}s" repeatCount="indefinite" calcMode="linear"/>

      <g opacity="0.9">
        <path d="M 0 13 L -26 {GRID_Y0 + 6 * GRID_ROW_GAP - SATELLITE_Y + 12:.2f} L 26 {GRID_Y0 + 6 * GRID_ROW_GAP - SATELLITE_Y + 12:.2f} Z"
          fill="url(#scanBeam)"/>
        <line x1="0" y1="14" x2="0" y2="{GRID_Y0 + 6 * GRID_ROW_GAP - SATELLITE_Y + 12:.2f}"
          stroke="{palette['beam']}" stroke-width="1" stroke-dasharray="3 8" opacity="0.65">
          <animate attributeName="stroke-dashoffset" from="0" to="-22" dur="1.1s" repeatCount="indefinite"/>
        </line>
      </g>

      <g filter="url(#satGlow)" transform="scale(0.58)">
        <path d="M -35 0 L -23 0 M 23 0 L 35 0" stroke="{palette['body_edge']}" stroke-width="2.4" stroke-linecap="round"/>
        <rect x="-56" y="-10" width="21" height="20" rx="2.5" fill="{palette['solar']}" stroke="{palette['solar_grid']}" stroke-width="1.2"/>
        <path d="M -49 -10 V 10 M -42 -10 V 10 M -56 0 H -35" stroke="{palette['solar_grid']}" stroke-width="0.8" opacity="0.72"/>
        <rect x="35" y="-10" width="21" height="20" rx="2.5" fill="{palette['solar']}" stroke="{palette['solar_grid']}" stroke-width="1.2"/>
        <path d="M 42 -10 V 10 M 49 -10 V 10 M 35 0 H 56" stroke="{palette['solar_grid']}" stroke-width="0.8" opacity="0.72"/>
        <rect x="-23" y="-15" width="46" height="30" rx="7" fill="{palette['body']}" stroke="{palette['body_edge']}" stroke-width="1.7"/>
        <rect x="-11" y="-7" width="22" height="14" rx="3" fill="{palette['panel_alt']}" stroke="{palette['orbit']}" stroke-width="1.3"/>
        <circle cx="0" cy="0" r="3.8" fill="{palette['orbit']}">
          <animate attributeName="opacity" values="0.4;1;0.4" dur="1.3s" repeatCount="indefinite"/>
        </circle>
        <path d="M 0 -15 V -27" stroke="{palette['body_edge']}" stroke-width="1.7" stroke-linecap="round"/>
        <circle cx="0" cy="-28" r="2.4" fill="{palette['orbit']}"/>
        <path d="M 5 -30 Q 13 -36 18 -28" fill="none" stroke="{palette['orbit']}" stroke-width="1.6" stroke-linecap="round">
          <animate attributeName="opacity" values="0.15;0.95;0.15" dur="1.2s" repeatCount="indefinite"/>
        </path>
        <path d="M -28 0 H -45" stroke="{palette['orbit']}" stroke-width="2" stroke-linecap="round" opacity="0.7">
          <animate attributeName="stroke-dasharray" values="2 12;8 6;2 12" dur="1.05s" repeatCount="indefinite"/>
        </path>
      </g>
    </g>'''


def render_svg(calendar: Calendar, login: str, theme: str) -> str:
    palette = PALETTES[theme]
    days = flatten_days(calendar)
    max_count = max((day.count for day in days), default=0)
    active_days = sum(day.count > 0 for day in days)
    best_streak = longest_streak(days)
    week_count = len(calendar.weeks)

    signals: list[str] = []
    week_scans: list[str] = []
    for week_index, week in enumerate(calendar.weeks):
        x = x_for_week(week_index, week_count)
        delay = scan_delay(week_index, week_count)
        week_scans.append(render_week_scan(x, palette, delay))
        for day in week:
            y = y_for_weekday(day.weekday)
            level = level_for(day.count, max_count)
            signals.append(render_signal(x, y, day, level, palette, delay))

    months = "".join(
        f'<text x="{x:.2f}" y="115" fill="{palette["muted"]}" font-size="9.5" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">{label}</text>'
        for x, label in month_labels(calendar)
        if x <= GRID_X1 - 15
    )
    suffix = "DEMO DATA" if calendar.demo else "LIVE GITHUB DATA"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(login)} animated GitHub contribution satellite scan</title>
  <desc id="desc">A CubeSat scans one year of GitHub contributions from left to right. Horizontal position represents time, vertical position represents weekday, and signal intensity represents contribution count.</desc>
  <defs>
    <linearGradient id="panelFill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{palette['panel']}"/>
      <stop offset="1" stop-color="{palette['background']}"/>
    </linearGradient>
    <linearGradient id="scanBeam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{palette['beam']}" stop-opacity="0.30"/>
      <stop offset="0.55" stop-color="{palette['beam']}" stop-opacity="0.08"/>
      <stop offset="1" stop-color="{palette['beam']}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="trackGradient" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{palette['orbit']}" stop-opacity="0.18"/>
      <stop offset="0.5" stop-color="{palette['orbit']}" stop-opacity="0.82"/>
      <stop offset="1" stop-color="{palette['accent']}" stop-opacity="0.28"/>
    </linearGradient>
    <filter id="signalGlow" x="-180%" y="-180%" width="460%" height="460%">
      <feGaussianBlur stdDeviation="2.0" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="satGlow" x="-140%" y="-160%" width="380%" height="420%">
      <feGaussianBlur stdDeviation="3.0" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="panelClip"><rect x="1" y="1" width="998" height="348" rx="24"/></clipPath>
  </defs>

  <rect x="1" y="1" width="998" height="348" rx="24" fill="url(#panelFill)" stroke="{palette['border']}" stroke-width="2"/>

  <g clip-path="url(#panelClip)">
    <circle cx="930" cy="12" r="150" fill="{palette['orbit']}" opacity="0.035"/>
    <circle cx="45" cy="350" r="145" fill="{palette['accent']}" opacity="0.035"/>

    <g transform="translate(32 24)">
      <rect width="12" height="12" rx="3" fill="{palette['orbit']}"/>
      <circle cx="6" cy="6" r="2.1" fill="{palette['panel']}"/>
      <text x="22" y="11" fill="{palette['text']}" font-size="16" font-weight="700" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="1.1">{escape(login.upper())} // CONTRIBUTION SCAN</text>
      <text x="22" y="29" fill="{palette['muted']}" font-size="10.3" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" letter-spacing="0.95">{suffix} · 1 PASS = 1 YEAR · LEFT TO RIGHT</text>
    </g>

    <g transform="translate(683 18)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
      <rect x="0" y="0" width="92" height="44" rx="10" fill="{palette['panel_alt']}" stroke="{palette['border']}"/>
      <text x="46" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.4" letter-spacing="0.9">CONTRIBUTIONS</text>
      <text x="46" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{calendar.total}</text>
      <rect x="101" y="0" width="92" height="44" rx="10" fill="{palette['panel_alt']}" stroke="{palette['border']}"/>
      <text x="147" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.4" letter-spacing="0.9">ACTIVE DAYS</text>
      <text x="147" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{active_days}</text>
      <rect x="202" y="0" width="92" height="44" rx="10" fill="{palette['panel_alt']}" stroke="{palette['border']}"/>
      <text x="248" y="18" text-anchor="middle" fill="{palette['muted']}" font-size="8.4" letter-spacing="0.9">BEST STREAK</text>
      <text x="248" y="35" text-anchor="middle" fill="{palette['text']}" font-size="15" font-weight="700">{best_streak}d</text>
    </g>

    <path d="M {GRID_X0:.2f} {SATELLITE_Y:.2f} H {GRID_X1:.2f}" fill="none" stroke="url(#trackGradient)" stroke-width="1.4" stroke-linecap="round" stroke-dasharray="3 8" opacity="0.82">
      <animate attributeName="stroke-dashoffset" from="0" to="-44" dur="2.6s" repeatCount="indefinite"/>
    </path>
    <circle cx="{GRID_X0:.2f}" cy="{SATELLITE_Y:.2f}" r="3" fill="{palette['orbit']}" opacity="0.7"/>
    <circle cx="{GRID_X1:.2f}" cy="{SATELLITE_Y:.2f}" r="3" fill="{palette['accent']}" opacity="0.7"/>

    {months}
    <g fill="{palette['muted']}" font-size="9.5" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" text-anchor="end">
      <text x="101" y="136">SUN</text>
      <text x="101" y="174">TUE</text>
      <text x="101" y="212">THU</text>
      <text x="101" y="250">SAT</text>
    </g>

    <g opacity="0.52">
      <line x1="{GRID_X0}" y1="{GRID_Y0}" x2="{GRID_X1}" y2="{GRID_Y0}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
      <line x1="{GRID_X0}" y1="{GRID_Y0 + 2 * GRID_ROW_GAP}" x2="{GRID_X1}" y2="{GRID_Y0 + 2 * GRID_ROW_GAP}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
      <line x1="{GRID_X0}" y1="{GRID_Y0 + 4 * GRID_ROW_GAP}" x2="{GRID_X1}" y2="{GRID_Y0 + 4 * GRID_ROW_GAP}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
      <line x1="{GRID_X0}" y1="{GRID_Y0 + 6 * GRID_ROW_GAP}" x2="{GRID_X1}" y2="{GRID_Y0 + 6 * GRID_ROW_GAP}" stroke="{palette['grid']}" stroke-width="0.7" stroke-dasharray="2 8"/>
    </g>

    <g aria-label="Sequential weekly scan">{''.join(week_scans)}</g>
    <g aria-label="Contribution signals">{''.join(signals)}</g>
    {render_satellite(palette)}

    <g transform="translate(34 318)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="9.5" fill="{palette['muted']}">
      <circle cx="4" cy="0" r="1.75" fill="{palette['zero']}"/>
      <circle cx="23" cy="0" r="2.35" fill="{palette['levels'][0]}"/>
      <circle cx="44" cy="0" r="2.95" fill="{palette['levels'][1]}"/>
      <circle cx="67" cy="0" r="3.65" fill="{palette['levels'][2]}"/>
      <circle cx="93" cy="0" r="4.45" fill="{palette['levels'][3]}" filter="url(#signalGlow)"/>
      <text x="111" y="4">daily signal strength</text>
    </g>

    <g transform="translate(701 312)" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
      <circle cx="0" cy="4" r="3" fill="{palette['good']}">
        <animate attributeName="opacity" values="0.45;1;0.45" dur="1.35s" repeatCount="indefinite"/>
      </circle>
      <text x="12" y="8" fill="{palette['muted']}" font-size="9.5" letter-spacing="1.0">SCANNER ONLINE · BUILD · LEARN · LAUNCH</text>
    </g>
  </g>
</svg>'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("GITHUB_USER", "DavCalo"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--demo", action="store_true", help="Generate deterministic preview data without GitHub")
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
