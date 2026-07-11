from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from debtmark.cli import (
    DEFAULT_EXCLUDES,
    Finding,
    main,
    new_since_baseline,
    read_baseline,
    render_markdown,
    scan,
    select_findings,
    write_baseline,
)


class ScanTests(unittest.TestCase):
    def test_finds_markers_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.py").write_text("# hack: later\n", encoding="utf-8")
            (root / "a.py").write_text("ok\n# TODO: one\n# fixme: two\n", encoding="utf-8")

            findings = scan(root)

            self.assertEqual(
                [(f.path, f.line, f.marker) for f in findings],
                [("a.py", 2, "TODO"), ("a.py", 3, "FIXME"), ("b.py", 1, "HACK")],
            )

    def test_skips_excluded_binary_large_and_symlink_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ignored").mkdir()
            (root / "ignored" / "x.py").write_text("# TODO hidden", encoding="utf-8")
            (root / "package.egg-info").mkdir()
            (root / "package.egg-info" / "PKG-INFO").write_text("TODO hidden", encoding="utf-8")
            (root / ".ruff_cache").mkdir()
            (root / ".ruff_cache" / "state").write_text("TODO hidden", encoding="utf-8")
            (root / "binary").write_bytes(b"TODO\0binary")
            (root / "large.txt").write_text("TODO " * 20, encoding="utf-8")
            target = root / "target.txt"
            target.write_text("TODO visible", encoding="utf-8")
            (root / "link.txt").symlink_to(target)

            findings = scan(root, excludes=(*DEFAULT_EXCLUDES, "ignored"), max_size=20)

            self.assertEqual([(f.path, f.line) for f in findings], [("target.txt", 1)])

    def test_custom_markers_are_literal_whole_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes").write_text("DEBT[1] later\nDEBT[1]x not this\n", encoding="utf-8")

            findings = scan(root, markers=("DEBT[1]",))

            self.assertEqual(len(findings), 1)

    def test_git_age_uses_blame_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "work.py").write_text("# TODO: old promise\n# FIXME: also old\n", encoding="utf-8")
            env = {
                "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
            }
            subprocess.run(["git", "add", "work.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "add work"], cwd=root, check=True, env={**__import__("os").environ, **env})

            with mock.patch("debtmark.cli.subprocess.run", wraps=subprocess.run) as run:
                findings = scan(
                    root, with_git_age=True, now=datetime(2020, 1, 11, tzinfo=timezone.utc)
                )

            self.assertEqual([finding.age_days for finding in findings], [10, 10])
            self.assertEqual(findings[0].committed_at, "2020-01-01T00:00:00+00:00")
            self.assertEqual(run.call_count, 1)

    def test_ignore_patterns_match_paths_components_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generated").mkdir()
            (root / "generated" / "x.py").write_text("# TODO hidden\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "keep.py").write_text("# TODO visible\n", encoding="utf-8")
            (root / "src" / "skip.gen.py").write_text("# TODO hidden\n", encoding="utf-8")

            findings = scan(root, ignore_patterns=("generated", "src/*.gen.py"))

            self.assertEqual([finding.path for finding in findings], ["src/keep.py"])

    def test_triage_filters_unknown_ages_and_sorts_oldest_first(self) -> None:
        findings = [
            Finding("a.py", 1, "TODO", "new", age_days=2),
            Finding("b.py", 1, "HACK", "unknown"),
            Finding("c.py", 1, "FIXME", "old", age_days=90),
            Finding("d.py", 1, "TODO", "middle", age_days=30),
        ]

        selected = select_findings(findings, min_age=30, order="age")

        self.assertEqual([finding.path for finding in selected], ["c.py", "d.py"])

    def test_triage_sorts_by_marker_with_path_tiebreaker(self) -> None:
        findings = [
            Finding("z.py", 1, "TODO", "later"),
            Finding("b.py", 2, "FIXME", "first"),
            Finding("a.py", 3, "FIXME", "second"),
        ]

        selected = select_findings(findings, order="marker")

        self.assertEqual([finding.path for finding in selected], ["a.py", "b.py", "z.py"])


class RenderAndCliTests(unittest.TestCase):
    def test_version(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            main(["--version"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(output.getvalue(), "debtmark 0.1.0\n")

    def test_markdown_escapes_table_pipes(self) -> None:
        output = render_markdown([Finding("a.py", 3, "TODO", "# TODO: a | b")], Path("/repo"))
        self.assertIn("a \\| b", output)

    def test_json_and_fail_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "x.py").write_text("# TODO: x\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([directory, "--format", "json", "--fail-on-findings"])

            payload = json.loads(output.getvalue())
            self.assertEqual(status, 1)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["findings"][0]["path"], "x.py")

    def test_invalid_path_returns_two(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            status = main(["/path/that/does/not/exist"])
        self.assertEqual(status, 2)
        self.assertIn("not a directory", error.getvalue())

    def test_baseline_ignores_line_moves_and_preserves_duplicate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x.py"
            baseline = root / ".debtmark.json"
            source.write_text("# TODO same\n# TODO same\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([directory, "--write-baseline", str(baseline)]), 0)
            source.write_text("new header\n# TODO same\n# TODO same\n# TODO same\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([directory, "--baseline", str(baseline), "--fail-on-findings"])

            self.assertEqual(status, 1)
            self.assertIn("x.py:4", output.getvalue())
            self.assertNotIn(".debtmark.json", output.getvalue())

    def test_invalid_baseline_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory, "baseline.json")
            baseline.write_text('{"version": 99, "findings": []}', encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                status = main([directory, "--baseline", str(baseline)])

            self.assertEqual(status, 2)
            self.assertIn("unsupported baseline version", error.getvalue())

    def test_default_ignore_file_and_missing_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".debtmarkignore").write_text("# generated code\nignored.py\n", encoding="utf-8")
            (root / "ignored.py").write_text("# TODO hidden\n", encoding="utf-8")
            (root / "kept.py").write_text("# TODO visible\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([directory]), 0)
            self.assertIn("kept.py:1", output.getvalue())
            self.assertNotIn("ignored.py", output.getvalue())

            error = io.StringIO()
            with redirect_stderr(error):
                status = main([directory, "--ignore-file", str(root / "missing")])
            self.assertEqual(status, 2)
            self.assertIn("ignore file not found", error.getvalue())

    def test_baseline_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory, "baseline.json")
            findings = [
                Finding("x.py", 1, "TODO", "# TODO same"),
                Finding("x.py", 9, "TODO", "# TODO same"),
            ]

            write_baseline(baseline, findings)
            counts = read_baseline(baseline)

            self.assertEqual(counts[("x.py", "TODO", "# TODO same")], 2)
            self.assertEqual(new_since_baseline(findings, counts), [])


if __name__ == "__main__":
    unittest.main()
