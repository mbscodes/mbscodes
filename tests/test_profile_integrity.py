from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProfileIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.workflow = (ROOT / ".github" / "workflows" / "snake.yml").read_text(
            encoding="utf-8"
        )

    def test_repository_count_uses_dynamic_github_api_badge(self):
        self.assertIn("img.shields.io/badge/dynamic/json", self.readme)
        self.assertIn("query=%24%2Epublic_repos", self.readme)
        self.assertIn("api.github.com%2Fusers%2Fmbscodes", self.readme)
        self.assertNotIn("Public_Repos-4-", self.readme)

    def test_streak_card_uses_generated_output(self):
        self.assertIn(
            "https://raw.githubusercontent.com/mbscodes/mbscodes/output/github-streak.svg",
            self.readme,
        )
        self.assertNotIn("streak-stats.demolab.com", self.readme)

    def test_snake_uses_light_and_dark_picture_sources(self):
        self.assertIn("<picture>", self.readme)
        self.assertIn('(prefers-color-scheme: dark)', self.readme)
        self.assertIn("github-contribution-grid-snake-dark.svg", self.readme)
        self.assertIn("github-contribution-grid-snake.svg", self.readme)

    def test_workflow_refreshes_and_publishes_all_profile_artifacts(self):
        self.assertIn('cron: "0 */6 * * *"', self.workflow)
        self.assertRegex(
            self.workflow,
            r"(?m)^concurrency:\n  group: profile-assets\n  cancel-in-progress: false$",
        )
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python scripts/generate_streak.py", self.workflow)
        self.assertIn("dist/github-streak.svg", self.workflow)

    def test_every_action_is_pinned_to_a_reviewed_full_sha(self):
        expected = {
            "actions/checkout": ("d23441a48e516b6c34aea4fa41551a30e30af803", "v6"),
            "Platane/snk/svg-only": ("d8f6715049803e982ee5ff501b6b9b7d5deeb09b", "v3"),
            "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4"),
            "actions/download-artifact": ("634f93cb2916e3fdff6788551b99b062d0335ce0", "v5"),
        }
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(\S+))?", self.workflow, re.M)

        self.assertEqual(len(uses), 5)
        for reference, version in uses:
            action, separator, sha = reference.partition("@")
            self.assertTrue(separator, f"Action is missing a ref: {reference}")
            self.assertIn(action, expected, f"Unreviewed action: {action}")
            expected_sha, expected_version = expected[action]
            self.assertEqual(sha, expected_sha)
            self.assertRegex(sha, r"^[0-9a-f]{40}$")
            self.assertEqual(version, expected_version)

        self.assertEqual(
            sum(reference.startswith("actions/checkout@") for reference, _ in uses),
            2,
        )

    def test_generation_job_is_read_only_and_exports_only_dist(self):
        generate, publish = self.workflow.split("\n  publish:", maxsplit=1)
        permissions = re.search(
            r"^    permissions:\n((?:      [^\n]+\n)+)", generate, re.M
        )

        self.assertIsNotNone(permissions)
        self.assertEqual(permissions.group(1).strip(), "contents: read")
        self.assertNotIn("contents: write", generate)
        self.assertIn("persist-credentials: false", generate)
        self.assertIn("name: profile-assets", generate)
        self.assertIn("path: |", generate)
        self.assertIn("if-no-files-found: error", generate)
        upload_paths = """path: |
            dist/github-streak.svg
            dist/github-contribution-grid-snake-dark.svg
            dist/github-contribution-grid-snake.svg"""
        self.assertIn(upload_paths, generate)
        self.assertNotIn("actions/upload-artifact", publish)

    def test_publish_job_is_isolated_and_pushes_only_expected_svgs(self):
        _, publish = self.workflow.split("\n  publish:", maxsplit=1)
        permissions = re.search(
            r"^    permissions:\n((?:      [^\n]+\n)+)", publish, re.M
        )

        self.assertIn("needs: generate", publish)
        self.assertIsNotNone(permissions)
        self.assertEqual(permissions.group(1).strip(), "contents: write")
        self.assertIn("ref: output", publish)
        self.assertIn("name: profile-assets", publish)
        self.assertIn("path: output", publish)
        self.assertIn("working-directory: output", publish)
        self.assertIn("git diff --cached --quiet", publish)
        self.assertIn("git push origin HEAD:output", publish)
        self.assertIn(
            "git add -- github-streak.svg github-contribution-grid-snake-dark.svg github-contribution-grid-snake.svg",
            publish,
        )
        self.assertNotIn("crazy-max/ghaction-github-pages", self.workflow)


if __name__ == "__main__":
    unittest.main()
