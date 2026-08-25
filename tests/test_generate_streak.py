import datetime as dt
import io
import json
import os
import tempfile
import urllib.error
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.generate_streak import (
    compute_streaks,
    fetch_contribution_days,
    main,
    render_svg,
)


def day(date, count):
    return {"date": date.isoformat(), "contributionCount": count}


class ComputeStreaksTests(unittest.TestCase):
    def test_current_streak_includes_today_when_today_is_active(self):
        today = dt.date(2026, 8, 25)
        days = [
            day(today - dt.timedelta(days=2), 1),
            day(today - dt.timedelta(days=1), 2),
            day(today, 3),
        ]

        self.assertEqual(compute_streaks(days, today=today), (6, 3, 3))

    def test_current_streak_starts_at_yesterday_when_today_is_inactive(self):
        today = dt.date(2026, 8, 25)
        days = [
            day(today - dt.timedelta(days=3), 4),
            day(today - dt.timedelta(days=2), 0),
            day(today - dt.timedelta(days=1), 2),
            day(today, 0),
        ]

        self.assertEqual(compute_streaks(days, today=today), (6, 1, 1))

    def test_streak_is_zero_when_today_and_yesterday_are_inactive(self):
        today = dt.date(2026, 8, 25)
        days = [day(today - dt.timedelta(days=2), 5), day(today, 0)]

        self.assertEqual(compute_streaks(days, today=today), (5, 0, 1))

    def test_empty_calendar_has_zero_stats(self):
        self.assertEqual(
            compute_streaks([], today=dt.date(2026, 8, 25)),
            (0, 0, 0),
        )

    def test_longest_streak_treats_missing_dates_as_inactive(self):
        start = dt.date(2026, 8, 1)
        days = [
            day(start, 1),
            day(start + dt.timedelta(days=1), 1),
            day(start + dt.timedelta(days=3), 3),
            day(start + dt.timedelta(days=4), 2),
            day(start + dt.timedelta(days=5), 1),
        ]

        self.assertEqual(
            compute_streaks(days, today=dt.date(2026, 8, 10)),
            (8, 0, 3),
        )

    def test_future_days_are_excluded_from_every_stat(self):
        today = dt.date(2026, 8, 25)
        days = [day(today, 2), day(today + dt.timedelta(days=1), 99)]

        self.assertEqual(compute_streaks(days, today=today), (2, 1, 1))


class RenderSvgTests(unittest.TestCase):
    def test_svg_is_accessible_and_escapes_dynamic_text(self):
        svg = render_svg("A <coder> & friends", total=12, current=2, longest=7)

        self.assertIn('role="img"', svg)
        self.assertIn('aria-labelledby="title description"', svg)
        self.assertIn("<title id=\"title\">", svg)
        self.assertIn("<desc id=\"description\">", svg)
        self.assertIn("A &lt;coder&gt; &amp; friends", svg)
        self.assertNotIn("A <coder> & friends", svg)
        self.assertIn("Current Streak (12 Months)", svg)
        self.assertIn("Total Contributions (Past 12 Months)", svg)
        self.assertIn("Longest Streak (12 Months)", svg)
        self.assertIn("in the past 12 months", svg)
        self.assertIn("current streak within the past 12 months", svg)
        ET.fromstring(svg)


class CliFailureTests(unittest.TestCase):
    def test_cli_writes_generated_svg(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "streak.svg"
            with (
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}),
                mock.patch(
                    "scripts.generate_streak.fetch_contribution_days",
                    return_value=[day(today, 2)],
                ),
                redirect_stdout(io.StringIO()),
            ):
                result = main(
                    ["--username", "mbscodes", "--output", str(output)]
                )

            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())
            ET.fromstring(output.read_text(encoding="utf-8"))

    def test_missing_token_fails_clearly(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stderr(stderr):
            result = main(["--username", "mbscodes"])

        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue().strip(), "error: GITHUB_TOKEN is required")

    def test_api_failure_does_not_leak_token(self):
        secret = "ghs_super-secret-value"
        failure = urllib.error.HTTPError(
            url="https://api.github.com/graphql",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as raised:
                fetch_contribution_days("mbscodes", secret)

        self.assertNotIn(secret, str(raised.exception))

    def test_successful_graphql_response_flattens_calendar_weeks(self):
        payload = {
            "data": {
                "user": {
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "weeks": [
                                {
                                    "contributionDays": [
                                        {"date": "2026-08-24", "contributionCount": 1}
                                    ]
                                },
                                {
                                    "contributionDays": [
                                        {"date": "2026-08-25", "contributionCount": 2}
                                    ]
                                },
                            ]
                        }
                    }
                }
            }
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with mock.patch("urllib.request.urlopen", return_value=response):
            days = fetch_contribution_days("mbscodes", "test-token")

        self.assertEqual(
            days,
            [
                {"date": "2026-08-24", "contributionCount": 1},
                {"date": "2026-08-25", "contributionCount": 2},
            ],
        )


if __name__ == "__main__":
    unittest.main()
