"""Command-line interface for debtmark."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .baseline import new_since_baseline, read_baseline, write_baseline
from .config import Config, read_config
from .core import (
    DEFAULT_EXCLUDES,
    DEFAULT_MARKERS,
    Finding,
    git_changed_files,
    git_files,
    read_ignore_file,
    scan,
    select_findings,
)
from .report import (
    render_csv,
    render_github,
    render_markdown,
    render_ndjson,
    render_sarif,
    render_summary,
    render_text,
)

# These imports are intentionally public here for compatibility with the original
# single-module API. New library users should import from core, baseline, or report.
__all__ = [
    "DEFAULT_EXCLUDES",
    "DEFAULT_MARKERS",
    "Finding",
    "main",
    "new_since_baseline",
    "read_baseline",
    "render_csv",
    "render_github",
    "render_markdown",
    "render_ndjson",
    "render_sarif",
    "render_summary",
    "render_text",
    "scan",
    "select_findings",
    "write_baseline",
]


def nonnegative_int(value: str) -> int:
    """Argparse converter for day counts."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def marker_value(value: str) -> str:
    """Argparse converter that rejects markers which match every line."""
    if not value.strip():
        raise argparse.ArgumentTypeError("marker must not be empty")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debtmark", description="Find TODO, FIXME, HACK, and XXX markers in a repository."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("path", nargs="?", default=".", type=Path)
    parser.add_argument("--config", type=Path, help="policy file (default: PATH/.debtmark-config.json)")
    parser.add_argument(
        "--marker",
        action="append",
        type=marker_value,
        dest="markers",
        help="marker to find; repeatable",
    )
    parser.add_argument("--exclude", action="append", default=[], help="file or directory name to skip")
    parser.add_argument(
        "--files",
        choices=("all", "git", "tracked"),
        default=None,
        help="file source: filesystem, Git non-ignored, or Git tracked only",
    )
    parser.add_argument("--changed", metavar="REVISION", help="scan files changed since a Git revision")
    parser.add_argument("--ignore-file", type=Path, help="glob file (default: PATH/.debtmarkignore)")
    parser.add_argument("--git-age", action="store_true", help="include the commit age of each line")
    parser.add_argument(
        "--min-age",
        type=nonnegative_int,
        metavar="DAYS",
        help="only show committed markers at least DAYS old",
    )
    parser.add_argument("--sort", choices=("path", "age", "marker"), default=None)
    parser.add_argument(
        "--format",
        choices=("text", "json", "ndjson", "csv", "markdown", "summary", "sarif", "github"),
        default=None,
    )
    parser.add_argument("--fail-on-findings", action="store_true", help="exit 1 when markers are found")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline", type=Path, help="report only findings absent from this baseline")
    baseline.add_argument("--write-baseline", type=Path, help="write all findings as a baseline and exit")
    return parser


def _load_ignore_patterns(args: argparse.Namespace, root: Path, excludes: list[str]) -> tuple[str, ...] | None:
    ignore_file = args.ignore_file
    explicit_ignore_file = ignore_file is not None
    if ignore_file is None:
        ignore_file = root / ".debtmarkignore"
    if ignore_file.exists():
        try:
            patterns = read_ignore_file(ignore_file)
        except (OSError, UnicodeError) as error:
            print(f"debtmark: cannot read ignore file {ignore_file}: {error}", file=sys.stderr)
            return None
        resolved_ignore = ignore_file.resolve()
        if resolved_ignore.parent == root or root in resolved_ignore.parents:
            excludes.append(ignore_file.name)
        return patterns
    if explicit_ignore_file:
        print(f"debtmark: ignore file not found: {ignore_file}", file=sys.stderr)
        return None
    return ()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.path.resolve()
    if not root.is_dir():
        print(f"debtmark: not a directory: {root}", file=sys.stderr)
        return 2

    config_path = args.config or root / ".debtmark-config.json"
    config = Config()
    if config_path.exists():
        try:
            config = read_config(config_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"debtmark: invalid config {config_path}: {error}", file=sys.stderr)
            return 2
    elif args.config is not None:
        print(f"debtmark: config file not found: {config_path}", file=sys.stderr)
        return 2

    markers = tuple(args.markers or config.markers or DEFAULT_MARKERS)
    baseline_path = args.baseline or args.write_baseline
    excludes = [*DEFAULT_EXCLUDES, *config.excludes, *args.exclude]
    resolved_config = config_path.resolve()
    if resolved_config.parent == root or root in resolved_config.parents:
        excludes.append(config_path.name)
    if baseline_path is not None:
        resolved_baseline = baseline_path.resolve()
        if resolved_baseline.parent == root or root in resolved_baseline.parents:
            excludes.append(baseline_path.name)

    ignore_patterns = _load_ignore_patterns(args, root, excludes)
    if ignore_patterns is None:
        return 2
    ignore_patterns = (*ignore_patterns, *config.ignore)
    min_age = args.min_age if args.min_age is not None else config.min_age
    sort_order = args.sort or config.sort or "path"
    output_format = args.format or config.format or "text"
    needs_git_age = args.git_age or min_age is not None or sort_order == "age"
    files = None
    file_mode = args.files or config.files or "all"
    if args.changed and args.files:
        print("debtmark: --changed and --files cannot be used together", file=sys.stderr)
        return 2
    if args.changed:
        files = git_changed_files(root, args.changed)
        if files is None:
            print(f"debtmark: cannot resolve changed files from {args.changed}", file=sys.stderr)
            return 2
    elif file_mode != "all":
        files = git_files(root, tracked_only=file_mode == "tracked")
        if files is None:
            print(f"debtmark: file mode {file_mode} requires a Git work tree", file=sys.stderr)
            return 2
    findings = scan(
        root,
        markers,
        excludes,
        needs_git_age,
        ignore_patterns=ignore_patterns,
        files=files,
    )

    if args.write_baseline:
        try:
            write_baseline(args.write_baseline, findings)
        except OSError as error:
            print(f"debtmark: cannot write baseline: {error}", file=sys.stderr)
            return 2
        print(f"debtmark: wrote {len(findings)} marker(s) to {args.write_baseline}")
        return 0
    if args.baseline:
        try:
            findings = new_since_baseline(findings, read_baseline(args.baseline))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"debtmark: invalid baseline {args.baseline}: {error}", file=sys.stderr)
            return 2

    findings = select_findings(findings, min_age, sort_order)
    if output_format == "json":
        print(
            json.dumps(
                {"root": str(root), "count": len(findings), "findings": [asdict(f) for f in findings]},
                indent=2,
            )
        )
    elif output_format == "ndjson":
        print(render_ndjson(findings))
    elif output_format == "csv":
        print(render_csv(findings), end="")
    elif output_format == "markdown":
        print(render_markdown(findings, root), end="")
    elif output_format == "summary":
        print(render_summary(findings, root))
    elif output_format == "sarif":
        print(render_sarif(findings))
    elif output_format == "github":
        print(render_github(findings))
    else:
        print(render_text(findings, root))
    return 1 if findings and args.fail_on_findings else 0


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """Run the CLI without a traceback when a downstream pipe closes early."""
    try:
        return main(argv)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(entrypoint())
