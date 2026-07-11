"""Command-line interface for debtmark."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence

from . import __version__

DEFAULT_MARKERS = ("TODO", "FIXME", "HACK", "XXX")
DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
)
BINARY_SAMPLE_SIZE = 8192
MAX_FILE_SIZE = 2 * 1024 * 1024
BASELINE_VERSION = 1


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    marker: str
    text: str
    committed_at: str | None = None
    age_days: int | None = None


def _finding_key(finding: Finding) -> tuple[str, str, str]:
    return finding.path, finding.marker, finding.text


def write_baseline(path: Path, findings: Sequence[Finding]) -> None:
    """Write stable finding identities and counts, deliberately omitting line numbers."""
    counts = Counter(_finding_key(finding) for finding in findings)
    entries = [
        {"path": key[0], "marker": key[1], "text": key[2], "count": count}
        for key, count in sorted(counts.items())
    ]
    path.write_text(
        json.dumps({"version": BASELINE_VERSION, "findings": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def read_baseline(path: Path) -> Counter[tuple[str, str, str]]:
    """Read and validate a baseline file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version (expected {BASELINE_VERSION})")
    entries = payload.get("findings")
    if not isinstance(entries, list):
        raise ValueError("baseline findings must be a list")
    counts: Counter[tuple[str, str, str]] = Counter()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("baseline finding must be an object")
        try:
            key = (entry["path"], entry["marker"], entry["text"])
            count = entry["count"]
        except KeyError as error:
            raise ValueError(f"baseline finding lacks {error.args[0]}") from error
        if not all(isinstance(value, str) for value in key) or not isinstance(count, int) or count < 1:
            raise ValueError("baseline finding has invalid values")
        counts[key] += count
    return counts


def new_since_baseline(
    findings: Sequence[Finding], baseline: Counter[tuple[str, str, str]]
) -> list[Finding]:
    """Return findings in excess of baseline counts, preserving scan order."""
    remaining = baseline.copy()
    new: list[Finding] = []
    for finding in findings:
        key = _finding_key(finding)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            new.append(finding)
    return new


def select_findings(
    findings: Sequence[Finding], min_age: int | None = None, order: str = "path"
) -> list[Finding]:
    """Filter and order findings for triage without mutating scan results."""
    selected = [
        finding
        for finding in findings
        if min_age is None or (finding.age_days is not None and finding.age_days >= min_age)
    ]
    if order == "age":
        return sorted(
            selected,
            key=lambda finding: (
                finding.age_days is None,
                -(finding.age_days or 0),
                finding.path,
                finding.line,
            ),
        )
    if order == "marker":
        return sorted(selected, key=lambda finding: (finding.marker, finding.path, finding.line))
    return selected


def nonnegative_int(value: str) -> int:
    """Argparse converter for day counts."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(BINARY_SAMPLE_SIZE)
    except OSError:
        return True


def read_ignore_file(path: Path) -> tuple[str, ...]:
    """Read simple glob patterns, ignoring blank lines and comments."""
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        pattern = line.strip()
        if pattern and not pattern.startswith("#"):
            patterns.append(pattern.rstrip("/"))
    return tuple(patterns)


def _matches_ignore(relative: str, patterns: Sequence[str]) -> bool:
    parts = relative.split("/")
    for pattern in patterns:
        if "/" in pattern:
            if fnmatchcase(relative, pattern) or relative.startswith(pattern + "/"):
                return True
        elif any(fnmatchcase(part, pattern) for part in parts):
            return True
    return False


def iter_files(
    root: Path, excludes: set[str], max_size: int, ignore_patterns: Sequence[str] = ()
) -> Iterable[Path]:
    """Yield candidate text files in stable order without following symlinks."""
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        kept_directories = []
        for name in sorted(dirnames):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if (
                name not in excludes
                and not name.endswith(".egg-info")
                and not path.is_symlink()
                and not _matches_ignore(relative, ignore_patterns)
            ):
                kept_directories.append(name)
        dirnames[:] = kept_directories
        for filename in sorted(filenames):
            path = Path(current) / filename
            relative = path.relative_to(root).as_posix()
            if filename in excludes or path.is_symlink() or _matches_ignore(relative, ignore_patterns):
                continue
            try:
                if path.stat().st_size > max_size or _is_binary(path):
                    continue
            except OSError:
                continue
            yield path


def _git_timestamps(root: Path, relative_path: str) -> dict[int, datetime]:
    """Return author timestamps by final line using one blame process per file."""
    command = ["git", "blame", "--line-porcelain", "--", relative_path]
    try:
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    timestamps: dict[int, datetime] = {}
    current_line: int | None = None
    for output_line in result.stdout.splitlines():
        header = re.match(r"^[0-9a-f^]+ \d+ (\d+)(?: \d+)?$", output_line)
        if header:
            current_line = int(header.group(1))
        elif current_line is not None and output_line.startswith("author-time "):
            try:
                value = int(output_line.removeprefix("author-time "))
            except ValueError:
                continue
            timestamps[current_line] = datetime.fromtimestamp(value, tz=timezone.utc)
    return timestamps


def scan(
    root: Path,
    markers: Sequence[str] = DEFAULT_MARKERS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
    with_git_age: bool = False,
    now: datetime | None = None,
    max_size: int = MAX_FILE_SIZE,
    ignore_patterns: Sequence[str] = (),
) -> list[Finding]:
    """Scan root and return debt markers in deterministic path/line order."""
    root = root.resolve()
    marker_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(m) for m in markers) + r")(?!\w)",
        re.IGNORECASE,
    )
    current_time = now or datetime.now(timezone.utc)
    findings: list[Finding] = []

    for path in iter_files(root, set(excludes), max_size, ignore_patterns):
        relative = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        matches: list[tuple[int, str, re.Match[str]]] = []
        for number, text in enumerate(lines, 1):
            match = marker_pattern.search(text)
            if match:
                matches.append((number, text, match))
        timestamps = _git_timestamps(root, relative) if with_git_age and matches else {}
        for number, text, match in matches:
            committed_at = None
            age_days = None
            timestamp = timestamps.get(number)
            if timestamp is not None:
                committed_at = timestamp.isoformat()
                age_days = max(0, (current_time - timestamp).days)
            findings.append(
                Finding(relative, number, match.group(1).upper(), text.strip(), committed_at, age_days)
            )
    return findings


def render_text(findings: Sequence[Finding], root: Path) -> str:
    lines = [f"debtmark: {len(findings)} marker(s) in {root}"]
    for item in findings:
        age = f" [{item.age_days}d]" if item.age_days is not None else ""
        lines.append(f"{item.path}:{item.line}: {item.marker}{age}  {item.text}")
    return "\n".join(lines)


def render_markdown(findings: Sequence[Finding], root: Path) -> str:
    lines = ["# Debt markers", "", f"Found **{len(findings)}** marker(s) in `{root}`.", ""]
    if not findings:
        return "\n".join(lines) + "No debt markers found.\n"
    lines += ["| Location | Marker | Age | Text |", "|---|---:|---:|---|"]
    for item in findings:
        location = f"`{item.path}:{item.line}`"
        age = f"{item.age_days}d" if item.age_days is not None else "—"
        text = item.text.replace("|", "\\|")
        lines.append(f"| {location} | {item.marker} | {age} | {text} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debtmark", description="Find TODO, FIXME, HACK, and XXX markers in a repository."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("path", nargs="?", default=".", type=Path)
    parser.add_argument("--marker", action="append", dest="markers", help="marker to find; repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="file or directory name to skip")
    parser.add_argument("--ignore-file", type=Path, help="glob file (default: PATH/.debtmarkignore)")
    parser.add_argument("--git-age", action="store_true", help="include the commit age of each line")
    parser.add_argument(
        "--min-age",
        type=nonnegative_int,
        metavar="DAYS",
        help="only show committed markers at least DAYS old",
    )
    parser.add_argument("--sort", choices=("path", "age", "marker"), default="path")
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    parser.add_argument("--fail-on-findings", action="store_true", help="exit 1 when markers are found")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline", type=Path, help="report only findings absent from this baseline")
    baseline.add_argument("--write-baseline", type=Path, help="write all findings as a baseline and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.path.resolve()
    if not root.is_dir():
        print(f"debtmark: not a directory: {root}", file=sys.stderr)
        return 2
    markers = tuple(args.markers or DEFAULT_MARKERS)
    baseline_path = args.baseline or args.write_baseline
    excludes = [*DEFAULT_EXCLUDES, *args.exclude]
    if baseline_path is not None:
        resolved_baseline = baseline_path.resolve()
        if resolved_baseline.parent == root or root in resolved_baseline.parents:
            excludes.append(baseline_path.name)
    ignore_file = args.ignore_file
    explicit_ignore_file = ignore_file is not None
    if ignore_file is None:
        ignore_file = root / ".debtmarkignore"
    ignore_patterns: tuple[str, ...] = ()
    if ignore_file.exists():
        try:
            ignore_patterns = read_ignore_file(ignore_file)
        except (OSError, UnicodeError) as error:
            print(f"debtmark: cannot read ignore file {ignore_file}: {error}", file=sys.stderr)
            return 2
        resolved_ignore = ignore_file.resolve()
        if resolved_ignore.parent == root or root in resolved_ignore.parents:
            excludes.append(ignore_file.name)
    elif explicit_ignore_file:
        print(f"debtmark: ignore file not found: {ignore_file}", file=sys.stderr)
        return 2
    needs_git_age = args.git_age or args.min_age is not None or args.sort == "age"
    findings = scan(root, markers, excludes, needs_git_age, ignore_patterns=ignore_patterns)
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
    findings = select_findings(findings, args.min_age, args.sort)
    if args.format == "json":
        print(
            json.dumps(
                {"root": str(root), "count": len(findings), "findings": [asdict(f) for f in findings]},
                indent=2,
            )
        )
    elif args.format == "markdown":
        print(render_markdown(findings, root), end="")
    else:
        print(render_text(findings, root))
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
