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
            markdown = self.run_debtmark(root, "--format", "markdown")
            summary = self.run_debtmark(root, "--format", "summary")
            sarif = self.run_debtmark(root, "--format", "sarif")

            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("work.py:1: TODO", text.stdout)
            self.assertEqual(json.loads(structured.stdout)["count"], 1)
            self.assertIn("| `work.py:1` | TODO |", markdown.stdout)
            self.assertIn("1 marker(s) across 1 file(s)", summary.stdout)
            self.assertEqual(json.loads(sarif.stdout)["runs"][0]["results"][0]["ruleId"], "TODO")

    def test_fail_on_findings_is_visible_to_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work.py").write_text("# FIXME: broken\n", encoding="utf-8")

            result = self.run_debtmark(root, "--fail-on-findings")

            self.assertEqual(result.returncode, 1)
            self.assertIn("FIXME", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_blank_markers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_debtmark(Path(directory), "--marker", "   ")

            self.assertEqual(result.returncode, 2)
            self.assertIn("marker must not be empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
