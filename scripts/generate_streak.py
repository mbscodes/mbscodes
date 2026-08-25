#!/usr/bin/env python3
"""Generate a self-hosted GitHub contribution streak card."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from typing import Iterable, Mapping


GRAPHQL_URL = "https://api.github.com/graphql"
CONTRIBUTIONS_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""


def _calendar(days: Iterable[Mapping[str, object]]) -> dict[dt.date, int]:
    """Normalize contribution days into a date-to-count calendar."""
    calendar: dict[dt.date, int] = {}
    for day in days:
        try:
            date = dt.date.fromisoformat(str(day["date"]))
            count = int(day["contributionCount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid contribution day data") from exc
        if count < 0:
            raise ValueError("Contribution counts cannot be negative")
        if date in calendar:
            raise ValueError(f"Duplicate contribution date: {date.isoformat()}")
        calendar[date] = count
    return calendar


def compute_streaks(
    days: Iterable[Mapping[str, object]], *, today: dt.date | None = None
) -> tuple[int, int, int]:
    """Return total contributions, current streak, and longest streak.

    A streak remains current until the end of the following day. Therefore, an
    inactive today does not erase a streak that was active yesterday.
    """
    calendar = _calendar(days)
    today = today or dt.datetime.now(dt.timezone.utc).date()
    total = sum(count for date, count in calendar.items() if date <= today)

    longest = 0
    running = 0
    previous: dt.date | None = None
    for date in sorted(calendar):
        if date > today:
            continue
        if calendar[date] <= 0:
            running = 0
        elif previous == date - dt.timedelta(days=1):
            running += 1
        else:
            running = 1
        longest = max(longest, running)
        previous = date

    anchor = today if calendar.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current = 0
    while calendar.get(anchor, 0) > 0:
        current += 1
        anchor -= dt.timedelta(days=1)

    return total, current, longest


def render_svg(username: str, *, total: int, current: int, longest: int) -> str:
    """Render streak values as a compact accessible SVG card."""
    safe_username = escape(username, quote=True)
    title = f"{safe_username}'s GitHub contribution streak"
    description = (
        f"{total} total contributions in the past 12 months, "
        f"{current} day current streak within the past 12 months, and "
        f"{longest} day longest streak "
        "in the past 12 months."
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="700" height="190" viewBox="0 0 700 190" role="img" aria-labelledby="title description">
  <title id="title">{title}</title>
  <desc id="description">{description}</desc>
  <style>
    .card {{ fill: #0d1117; stroke: #30363d; }}
    .value {{ fill: #38bdf8; font: 700 34px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .label {{ fill: #c9d1d9; font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: .2px; }}
    .divider {{ stroke: #30363d; }}
  </style>
  <rect class="card" x="1" y="1" width="698" height="188" rx="12"/>
  <line class="divider" x1="233" y1="36" x2="233" y2="154"/>
  <line class="divider" x1="467" y1="36" x2="467" y2="154"/>
  <g text-anchor="middle">
    <text class="value" x="117" y="88">{total}</text>
    <text class="label" x="117" y="119">Total Contributions (Past 12 Months)</text>
    <text class="value" x="350" y="88">{current}</text>
    <text class="label" x="350" y="119">Current Streak (12 Months)</text>
    <text class="value" x="583" y="88">{longest}</text>
    <text class="label" x="583" y="119">Longest Streak (12 Months)</text>
  </g>
</svg>
"""


def fetch_contribution_days(username: str, token: str) -> list[dict[str, object]]:
    """Fetch public contribution-calendar days from GitHub's GraphQL API."""
    body = json.dumps(
        {"query": CONTRIBUTIONS_QUERY, "variables": {"login": username}}
    ).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-streak-generator",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"GitHub GraphQL request failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach the GitHub GraphQL API") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("GitHub GraphQL returned an invalid response") from exc

    if not isinstance(payload, dict) or payload.get("errors"):
        raise RuntimeError("GitHub GraphQL returned an API error")

    try:
        user = payload["data"]["user"]
        weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
        return [day for week in weeks for day in week["contributionDays"]]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("GitHub GraphQL response is missing contribution data") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default=os.environ.get("GITHUB_REPOSITORY_OWNER"),
        help="GitHub username (defaults to GITHUB_REPOSITORY_OWNER)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/github-streak.svg"),
        help="SVG output path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not args.username:
        print("error: provide --username or GITHUB_REPOSITORY_OWNER", file=sys.stderr)
        return 2
    if not token:
        print("error: GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    try:
        days = fetch_contribution_days(args.username, token)
        total, current, longest = compute_streaks(days)
        svg = render_svg(
            args.username, total=total, current=current, longest=longest
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Generated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
