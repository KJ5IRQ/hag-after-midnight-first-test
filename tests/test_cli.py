from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from debtmark import __version__
from debtmark.cli import (
    DEFAULT_EXCLUDES,
    Finding,
    entrypoint,
    git_changed_files,
    git_files,
    main,
    new_since_baseline,
    read_baseline,
    render_csv,
    render_github,
    render_markdown,
    render_ndjson,
    render_sarif,
    render_summary,
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

    def test_overlapping_markers_prefer_longest_literal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes").write_text(
                "DEBT-SECURITY audit this\nDEBT ordinary\n", encoding="utf-8"
            )

            findings = scan(root, markers=("DEBT", "DEBT-SECURITY"))

            self.assertEqual(
                [finding.marker for finding in findings], ["DEBT-SECURITY", "DEBT"]
            )

    def test_empty_marker_sequence_finds_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work.py").write_text("ordinary line\n", encoding="utf-8")

            self.assertEqual(scan(root, markers=()), [])

    def test_marker_regex_supports_project_specific_tokenization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work.py").write_text(
                "# debt(api): migrate\n# debt-ops: rotate\n# debt: too vague\n",
                encoding="utf-8",
            )

            findings = scan(root, marker_regex=r"debt(?:\([a-z]+\)|-[a-z]+)")

            self.assertEqual(
                [(finding.line, finding.marker) for finding in findings],
                [(1, "DEBT(API)"), (2, "DEBT-OPS")],
            )

    def test_suppression_directives_skip_line_next_line_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lines.py").write_text(
                "# TODO: kept\n"
                "# TODO: inline  # debtmark: ignore\n"
                "# debtmark: ignore-next-line\n"
                "# FIXME: next\n"
                "# HACK: kept too\n",
                encoding="utf-8",
            )
            (root / "whole.py").write_text(
                "# debtmark: ignore-file\n# TODO: hidden\n", encoding="utf-8"
            )

            findings = scan(root)

            self.assertEqual(
                [(finding.line, finding.marker) for finding in findings],
                [(1, "TODO"), (5, "HACK")],
            )

    def test_suppression_directive_can_skip_several_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lines.py").write_text(
                "# debtmark: ignore-next 3 lines\n"
                "# TODO: hidden\n"
                "ordinary line\n"
                "# FIXME: hidden too\n"
                "# HACK: visible\n",
                encoding="utf-8",
            )

            findings = scan(root)

            self.assertEqual(
                [(finding.line, finding.marker) for finding in findings], [(5, "HACK")]
            )

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
            with (root / "work.py").open("a", encoding="utf-8") as source:
                source.write("# HACK: uncommitted\n")

            with mock.patch("debtmark.core.subprocess.run", wraps=subprocess.run) as run:
                findings = scan(
                    root, with_git_age=True, now=datetime(2020, 1, 11, tzinfo=timezone.utc)
                )

            self.assertEqual([finding.age_days for finding in findings], [10, 10, None])
            self.assertEqual(findings[0].committed_at, "2020-01-01T00:00:00+00:00")
            blame_calls = [call for call in run.call_args_list if call.args[0][:2] == ["git", "blame"]]
            self.assertEqual(len(blame_calls), 1)

    def test_shallow_clone_reports_unknown_git_age(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory, "upstream")
            clone = Path(directory, "clone")
            subprocess.run(["git", "init", "-q", upstream], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=upstream, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=upstream, check=True)
            (upstream / "work.py").write_text("# DEBT: inherited\n", encoding="utf-8")
            subprocess.run(["git", "add", "work.py"], cwd=upstream, check=True)
            old = {"GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00"}
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=upstream, check=True, env={**__import__("os").environ, **old})
            (upstream / "later.py").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "later.py"], cwd=upstream, check=True)
            recent = {"GIT_AUTHOR_DATE": "2021-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2021-01-01T00:00:00+00:00"}
            subprocess.run(["git", "commit", "-qm", "later"], cwd=upstream, check=True, env={**__import__("os").environ, **recent})
            subprocess.run(["git", "clone", "-q", "--depth", "1", upstream.as_uri(), clone], check=True)

            findings = scan(clone, markers=("DEBT",), with_git_age=True, now=datetime(2022, 1, 1, tzinfo=timezone.utc))

            self.assertEqual([finding.age_days for finding in findings], [None])
            self.assertIsNone(findings[0].committed_at)

    def test_non_git_age_scan_does_not_blame_each_marked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("# DEBT: one\n", encoding="utf-8")
            (root / "b.py").write_text("# DEBT: two\n", encoding="utf-8")
            with mock.patch("debtmark.core.subprocess.run", wraps=subprocess.run) as run:
                findings = scan(root, markers=("DEBT",), with_git_age=True)

            self.assertEqual([finding.age_days for finding in findings], [None, None])
            self.assertEqual(len(run.call_args_list), 1)

    def test_git_file_selection_honors_ignores_and_tracked_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
            (root / "tracked.py").write_text("# TODO: tracked\n", encoding="utf-8")
            (root / "untracked.py").write_text("# FIXME: untracked\n", encoding="utf-8")
            (root / "ignored.py").write_text("# HACK: ignored\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "tracked.py"], cwd=root, check=True)

            selected = git_files(root)
            tracked = git_files(root, tracked_only=True)

            self.assertIsNotNone(selected)
            self.assertIsNotNone(tracked)
            self.assertEqual(
                [finding.marker for finding in scan(root, files=selected)], ["TODO", "FIXME"]
            )
            self.assertEqual([finding.marker for finding in scan(root, files=tracked)], ["TODO"])

    def test_changed_file_selection_uses_revision_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "changed.py").write_text("clean\n", encoding="utf-8")
            (root / "same.py").write_text("# TODO: existing\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            (root / "changed.py").write_text("# FIXME: new\n", encoding="utf-8")

            files = git_changed_files(root, "HEAD")

            self.assertIsNotNone(files)
            self.assertEqual([finding.path for finding in scan(root, files=files)], ["changed.py"])

    def test_changed_file_selection_accepts_annotated_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "changed.py").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "changed.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            subprocess.run(["git", "tag", "-a", "v1", "-m", "version one"], cwd=root, check=True)
            (root / "changed.py").write_text("changed\n", encoding="utf-8")

            files = git_changed_files(root, "v1")

            self.assertEqual(files, [root / "changed.py"])

    def test_changed_file_selection_accepts_branch_and_commit_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "changed.py").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "changed.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base_id = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()
            subprocess.run(["git", "branch", "baseline", base_id], cwd=root, check=True)
            (root / "changed.py").write_text("changed\n", encoding="utf-8")

            for revision in ("baseline", base_id):
                with self.subTest(revision=revision):
                    self.assertEqual(git_changed_files(root, revision), [root / "changed.py"])

    def test_changed_file_selection_rejects_option_like_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "work.py").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "work.py"], cwd=root, check=True)

            self.assertIsNone(git_changed_files(root, "--cached"))

    def test_cli_rejects_option_like_changed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "work.py").write_text("clean\n", encoding="utf-8")
            error = io.StringIO()

            with redirect_stderr(error):
                status = main([directory, "--changed=--cached"])

            self.assertEqual(status, 2)
            self.assertIn("cannot resolve changed files", error.getvalue())

    def test_changed_file_selection_is_relative_to_nested_scan_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            root = repository / "app"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
            (root / "inside.py").write_text("clean\n", encoding="utf-8")
            (repository / "outside.py").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
            (root / "inside.py").write_text("# TODO: inside\n", encoding="utf-8")
            (repository / "outside.py").write_text("# FIXME: outside\n", encoding="utf-8")

            files = git_changed_files(root, "HEAD")

            self.assertEqual(files, [root / "inside.py"])
            self.assertEqual([finding.path for finding in scan(root, files=files)], ["inside.py"])

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

    def test_ignore_directory_patterns_accept_trailing_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generated").mkdir()
            (root / "generated" / "x.py").write_text("# TODO hidden\n", encoding="utf-8")
            (root / "keep.py").write_text("# TODO visible\n", encoding="utf-8")

            findings = scan(root, ignore_patterns=("generated/",))

            self.assertEqual([finding.path for finding in findings], ["keep.py"])

    def test_anchored_ignore_patterns_only_match_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "policy.json").write_text("TODO hidden\n", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "policy.json").write_text("TODO visible\n", encoding="utf-8")

            findings = scan(root, ignore_patterns=("/policy.json",))

            self.assertEqual([finding.path for finding in findings], ["nested/policy.json"])

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
        self.assertEqual(output.getvalue(), f"debtmark {__version__}\n")

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib was added in Python 3.11")
    def test_runtime_version_matches_project_metadata(self) -> None:
        import tomllib

        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(__version__, project["project"]["version"])

    def test_entrypoint_swallows_broken_pipe(self) -> None:
        with mock.patch("debtmark.cli.main", side_effect=BrokenPipeError):
            self.assertEqual(entrypoint([]), 0)

    def test_markdown_escapes_table_pipes(self) -> None:
        output = render_markdown(
            [Finding("a|<b>.py", 3, "DEBT|OPS", "# DEBT|OPS: a | <b>")], Path("/repo")
        )

        self.assertIn(
            "| <code>a&#124;&lt;b&gt;.py:3</code> | DEBT&#124;OPS | — | "
            "# DEBT&#124;OPS: a &#124; &lt;b&gt; |",
            output,
        )
    def test_summary_groups_markers_files_and_age_buckets(self) -> None:
        findings = [
            Finding("a.py", 1, "TODO", "young", age_days=2),
            Finding("a.py", 2, "TODO", "old", age_days=400),
            Finding("b.py", 1, "FIXME", "middle", age_days=100),
            Finding("c.py", 1, "HACK", "uncommitted"),
        ]

        output = render_summary(findings, Path("/repo"))

        self.assertIn("4 marker(s) across 3 file(s)", output)
        self.assertIn("FIXME  1", output)
        self.assertIn("TODO   2", output)
        self.assertIn("top files:", output)
        self.assertIn("a.py  2", output)
        self.assertIn("<30d     1", output)
        self.assertIn(">=365d   1", output)
        self.assertIn("unknown  1", output)

    def test_sarif_contains_rules_locations_and_age_properties(self) -> None:
        findings = [
            Finding(
                "src/a b#café%/d.py",
                7,
                "DEBT",
                "# DEBT: remove shim",
                "2025-01-01T00:00:00+00:00",
                90,
            ),
            Finding("src/b.py", 2, "FIXME", "# FIXME: race"),
        ]

        payload = json.loads(render_sarif(findings))

        self.assertEqual(payload["version"], "2.1.0")
        run = payload["runs"][0]
        self.assertEqual([rule["id"] for rule in run["tool"]["driver"]["rules"]], ["DEBT", "FIXME"])
        first = run["results"][0]
        self.assertEqual(
            first["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
            "src/a%20b%23caf%C3%A9%25/d.py",
        )
        self.assertEqual(first["locations"][0]["physicalLocation"]["region"]["startLine"], 7)
        self.assertEqual(first["properties"]["ageDays"], 90)

    def test_github_annotations_escape_commands_and_properties(self) -> None:
        output = render_github(
            [Finding("src/a,b.py", 7, "TODO", "# TODO: 50% done\nnext")]
        )

        self.assertEqual(
            output,
            "::warning file=src/a%2Cb.py,line=7,title=debtmark TODO::"
            "# TODO: 50%25 done%0Anext",
        )

    def test_csv_and_ndjson_preserve_structured_text(self) -> None:
        findings = [Finding("café.py", 3, "TODO", "# TODO: a, b")]

        csv_output = render_csv(findings)
        ndjson_output = render_ndjson(findings)

        self.assertEqual(csv_output.splitlines()[0], "path,line,marker,text,committed_at,age_days")
        self.assertIn('café.py,3,TODO,"# TODO: a, b",,', csv_output)
        self.assertEqual(json.loads(ndjson_output)["path"], "café.py")
        self.assertIn("café.py", ndjson_output)

    def test_empty_ndjson_output_has_no_blank_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([directory, "--format", "ndjson"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "")

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

    def test_baseline_rejects_boolean_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory, "baseline.json")
            baseline.write_text(
                '{"version": 1, "findings": [{"path": "x", "marker": "TODO", '
                '"text": "TODO", "count": true}]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid values"):
                read_baseline(baseline)

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

    def test_policy_files_do_not_exclude_unrelated_same_named_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "policy.json"
            nested = root / "nested"
            nested.mkdir()
            (nested / "policy.json").write_text("# TODO visible\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([directory, "--write-baseline", str(baseline)]), 0)

            counts = read_baseline(baseline)
            self.assertEqual(counts[("nested/policy.json", "TODO", "# TODO visible")], 1)

    def test_default_baseline_is_not_scanned_without_baseline_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".debtmark-baseline.json").write_text(
                '{"text": "TODO generated record"}\n', encoding="utf-8"
            )
            (root / "work.py").write_text("# FIXME visible\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                status = main([directory])

            self.assertEqual(status, 0)
            self.assertIn("work.py:1", output.getvalue())
            self.assertNotIn(".debtmark-baseline.json", output.getvalue())

    def test_failed_baseline_replace_preserves_original_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            baseline.write_text("original\n", encoding="utf-8")

            with mock.patch("debtmark.baseline.os.replace", side_effect=OSError("full disk")):
                with self.assertRaisesRegex(OSError, "full disk"):
                    write_baseline(
                        baseline, [Finding("x.py", 1, "TODO", "# TODO same")]
                    )

            self.assertEqual(baseline.read_text(encoding="utf-8"), "original\n")
            self.assertEqual([path.name for path in root.iterdir()], ["baseline.json"])


if __name__ == "__main__":
    unittest.main()
