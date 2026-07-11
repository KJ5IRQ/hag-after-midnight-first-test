from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from debtmark.cli import (
    Finding,
    main,
    new_since_baseline,
    read_baseline,
    render_markdown,
    scan,
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
            (root / "binary").write_bytes(b"TODO\0binary")
            (root / "large.txt").write_text("TODO " * 20, encoding="utf-8")
            target = root / "target.txt"
            target.write_text("TODO visible", encoding="utf-8")
            (root / "link.txt").symlink_to(target)

            findings = scan(root, excludes=("ignored",), max_size=20)

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
            (root / "work.py").write_text("# TODO: old promise\n", encoding="utf-8")
            env = {
                "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
            }
            subprocess.run(["git", "add", "work.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "add work"], cwd=root, check=True, env={**__import__("os").environ, **env})

            findings = scan(root, with_git_age=True, now=datetime(2020, 1, 11, tzinfo=timezone.utc))

            self.assertEqual(findings[0].age_days, 10)
            self.assertEqual(findings[0].committed_at, "2020-01-01T00:00:00+00:00")


class RenderAndCliTests(unittest.TestCase):
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
