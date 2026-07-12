from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class InstalledCliTests(unittest.TestCase):
    def run_debtmark(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "debtmark", str(root), *arguments],
            cwd=root.parent,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_all_report_formats_through_module_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "project")
            root.mkdir()
            (root / "work.py").write_text("# TODO: remove compatibility shim\n", encoding="utf-8")

            text = self.run_debtmark(root)
            structured = self.run_debtmark(root, "--format", "json")
            ndjson = self.run_debtmark(root, "--format", "ndjson")
            csv_output = self.run_debtmark(root, "--format", "csv")
            markdown = self.run_debtmark(root, "--format", "markdown")
            summary = self.run_debtmark(root, "--format", "summary")
            sarif = self.run_debtmark(root, "--format", "sarif")
            github = self.run_debtmark(root, "--format", "github")

            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("work.py:1: TODO", text.stdout)
            self.assertEqual(json.loads(structured.stdout)["count"], 1)
            self.assertEqual(json.loads(ndjson.stdout)["marker"], "TODO")
            self.assertTrue(csv_output.stdout.startswith("path,line,marker,text"))
            self.assertIn("| <code>work.py:1</code> | TODO |", markdown.stdout)
            self.assertIn("1 marker(s) across 1 file(s)", summary.stdout)
            self.assertEqual(json.loads(sarif.stdout)["runs"][0]["results"][0]["ruleId"], "TODO")
            self.assertIn("::warning file=work.py,line=1,title=debtmark TODO::", github.stdout)

    def test_fail_on_findings_is_visible_to_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work.py").write_text("# FIXME: broken\n", encoding="utf-8")

            result = self.run_debtmark(root, "--fail-on-findings")

            self.assertEqual(result.returncode, 1)
            self.assertIn("FIXME", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_count_and_silent_formats_support_shell_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work.py").write_text("# TODO one\n# FIXME two\n", encoding="utf-8")

            count = self.run_debtmark(root, "--format", "count")
            silent = self.run_debtmark(root, "--format", "none", "--fail-on-findings")

            self.assertEqual(count.stdout, "2\n")
            self.assertEqual(count.returncode, 0)
            self.assertEqual(silent.stdout, "")
            self.assertEqual(silent.stderr, "")
            self.assertEqual(silent.returncode, 1)

    def test_blank_markers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_debtmark(Path(directory), "--marker", "   ")

            self.assertEqual(result.returncode, 2)
            self.assertIn("marker must not be empty", result.stderr)

    def test_marker_regex_cli_and_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".debtmark-config.json").write_text(
                json.dumps({"marker_regex": r"DEBT-[A-Z]+"}), encoding="utf-8"
            )
            (root / "work.py").write_text(
                "# DEBT-API migrate\n# TODO ordinary\n", encoding="utf-8"
            )

            configured = self.run_debtmark(root, "--format", "json")
            overridden = self.run_debtmark(root, "--marker", "TODO", "--format", "json")
            invalid = self.run_debtmark(root, "--marker-regex", "[")
            empty_match = self.run_debtmark(root, "--marker-regex", r"(?=DEBT)")

            self.assertEqual(json.loads(configured.stdout)["findings"][0]["marker"], "DEBT-API")
            self.assertEqual(json.loads(overridden.stdout)["findings"][0]["marker"], "TODO")
            self.assertIn("invalid marker regex", invalid.stderr)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("must not produce empty matches", empty_match.stderr)
            self.assertEqual(empty_match.returncode, 2)

    def test_git_file_mode_requires_a_work_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_debtmark(Path(directory), "--files", "tracked")

            self.assertEqual(result.returncode, 2)
            self.assertIn("requires a Git work tree", result.stderr)

    def test_repository_config_sets_markers_excludes_and_ignore_globs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".debtmark-config.json").write_text(
                json.dumps(
                    {
                        "markers": ["DEBT"],
                        "exclude": ["vendor"],
                        "ignore": ["docs/*.txt"],
                        "sort": "marker",
                        "format": "ndjson",
                    }
                ),
                encoding="utf-8",
            )
            (root / "vendor").mkdir()
            (root / "vendor" / "x.py").write_text("# DEBT hidden\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "x.txt").write_text("DEBT hidden\n", encoding="utf-8")
            (root / "work.py").write_text("# TODO ignored\n# DEBT visible\n", encoding="utf-8")

            result = self.run_debtmark(root)
            overridden = self.run_debtmark(root, "--format", "text")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["marker"], "DEBT")
            self.assertNotIn("hidden", result.stdout)
            self.assertIn("work.py:2: DEBT", overridden.stdout)

    def test_unknown_config_fields_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "policy.json"
            config.write_text('{"markres": ["TODO"]}', encoding="utf-8")

            result = self.run_debtmark(root, "--config", str(config))

            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown config field: markres", result.stderr)

    def test_invalid_configured_age_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".debtmark-config.json").write_text(
                '{"min_age": true}', encoding="utf-8"
            )

            result = self.run_debtmark(root)

            self.assertEqual(result.returncode, 2)
            self.assertIn("min_age must be a non-negative integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
