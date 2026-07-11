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


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    marker: str
    text: str
    committed_at: str | None = None
    age_days: int | None = None


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
) -> list[Finding]:
    """Scan root and return debt markers in deterministic path/line order."""
    root = root.resolve()
    marker_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(marker) for marker in markers) + r")(?!\w)",
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
