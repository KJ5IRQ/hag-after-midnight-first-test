"""Scanning and triage primitives for debtmark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable, Sequence

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
IGNORE_FILE_PATTERN = re.compile(r"\bdebtmark:\s*ignore-file\b", re.IGNORECASE)
IGNORE_LINE_PATTERN = re.compile(r"\bdebtmark:\s*ignore(?:\s|$)", re.IGNORECASE)
IGNORE_NEXT_PATTERN = re.compile(
    r"\bdebtmark:\s*ignore-next(?:-line|\s+(\d+)\s+lines?)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    marker: str
    text: str
    committed_at: str | None = None
    age_days: int | None = None


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
    for raw_pattern in patterns:
        # Ignore-file loading normalizes directory-style patterns, but config
        # and library callers bypass that reader. Normalize at the shared seam.
        pattern = raw_pattern.rstrip("/")
        if not pattern:
            continue
        if pattern.startswith("/"):
            anchored = pattern.removeprefix("/")
            if fnmatchcase(relative, anchored) or relative.startswith(anchored + "/"):
                return True
            continue
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
                if path.stat().st_size > max_size:
                    continue
            except OSError:
                continue
            yield path


def git_files(root: Path, tracked_only: bool = False) -> list[Path] | None:
    """Return Git-selected files, or None when root is not in a work tree."""
    command = ["git", "ls-files", "-z", "--cached"]
    if not tracked_only:
        command.extend(("--others", "--exclude-standard"))
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def git_changed_files(root: Path, revision: str) -> list[Path] | None:
    """Return files added, copied, modified, or renamed since a Git revision."""
    command = [
        "git",
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMR",
        revision,
        "--",
    ]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def _select_explicit_files(
    root: Path,
    files: Sequence[Path],
    excludes: set[str],
    max_size: int,
    ignore_patterns: Sequence[str],
) -> Iterable[Path]:
    for path in sorted(files):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        parts = relative.split("/")
        if (
            any(part in excludes or part.endswith(".egg-info") for part in parts)
            or path.is_symlink()
            or _matches_ignore(relative, ignore_patterns)
        ):
            continue
        try:
            if not path.is_file() or path.stat().st_size > max_size:
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
        header = re.match(r"^([0-9a-f^]+) \d+ (\d+)(?: \d+)?$", output_line)
        if header:
            commit = header.group(1).lstrip("^")
            current_line = None if not commit.strip("0") else int(header.group(2))
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
    files: Sequence[Path] | None = None,
) -> list[Finding]:
    """Scan root and return debt markers in deterministic path/line order."""
    root = root.resolve()
    if not markers:
        return []
    # Prefer the most specific literal when configured markers share a prefix.
    # Regex alternation otherwise makes ("DEBT", "DEBT-SECURITY") report the
    # shorter marker merely because it was listed first.
    marker_pattern = re.compile(
        r"(?<!\w)("
        + "|".join(re.escape(marker) for marker in sorted(markers, key=len, reverse=True))
        + r")(?!\w)",
        re.IGNORECASE,
    )
    current_time = now or datetime.now(timezone.utc)
    findings: list[Finding] = []

    candidates = (
        iter_files(root, set(excludes), max_size, ignore_patterns)
        if files is None
        else _select_explicit_files(root, files, set(excludes), max_size, ignore_patterns)
    )
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:BINARY_SAMPLE_SIZE]:
            continue
        lines = data.decode(encoding="utf-8", errors="replace").splitlines()
        if any(IGNORE_FILE_PATTERN.search(line) for line in lines):
            continue
        matches: list[tuple[int, str, re.Match[str]]] = []
        ignored_lines = 0
        for number, text in enumerate(lines, 1):
            if ignored_lines:
                ignored_lines -= 1
                continue
            ignore_next = IGNORE_NEXT_PATTERN.search(text)
            if ignore_next:
                count = ignore_next.group(1)
                ignored_lines = int(count) if count is not None else 1
                continue
            if IGNORE_LINE_PATTERN.search(text):
                continue
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
