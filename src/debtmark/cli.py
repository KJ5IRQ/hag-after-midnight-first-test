"""Command-line interface for debtmark."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
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


def iter_files(root: Path, excludes: set[str], max_size: int) -> Iterable[Path]:
    """Yield candidate text files in stable order without following symlinks."""
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames if name not in excludes and not (Path(current) / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = Path(current) / filename
            if filename in excludes or path.is_symlink():
                continue
            try:
                if path.stat().st_size > max_size or _is_binary(path):
                    continue
            except OSError:
                continue
            yield path


def _git_timestamp(root: Path, relative_path: str, line: int) -> datetime | None:
    command = [
        "git", "blame", "--line-porcelain", f"-L{line},{line}", "--", relative_path
    ]
    try:
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"^author-time (\d+)$", result.stdout, re.MULTILINE)
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc)


def scan(
    root: Path,
    markers: Sequence[str] = DEFAULT_MARKERS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
    with_git_age: bool = False,
    now: datetime | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> list[Finding]:
    """Scan root and return debt markers in deterministic path/line order."""
    root = root.resolve()
    marker_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(m) for m in markers) + r")(?!\w)",
        re.IGNORECASE,
    )
    current_time = now or datetime.now(timezone.utc)
    findings: list[Finding] = []

    for path in iter_files(root, set(excludes), max_size):
        relative = path.relative_to(root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, text in enumerate(lines, 1):
            match = marker_pattern.search(text)
            if not match:
                continue
            committed_at = None
            age_days = None
            if with_git_age:
                timestamp = _git_timestamp(root, relative, number)
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
    parser.add_argument("path", nargs="?", default=".", type=Path)
    parser.add_argument("--marker", action="append", dest="markers", help="marker to find; repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="file or directory name to skip")
    parser.add_argument("--git-age", action="store_true", help="include the commit age of each line")
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    parser.add_argument("--fail-on-findings", action="store_true", help="exit 1 when markers are found")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.path.resolve()
    if not root.is_dir():
        print(f"debtmark: not a directory: {root}", file=sys.stderr)
        return 2
    markers = tuple(args.markers or DEFAULT_MARKERS)
    findings = scan(root, markers, (*DEFAULT_EXCLUDES, *args.exclude), args.git_age)
    if args.format == "json":
        print(json.dumps({"root": str(root), "count": len(findings), "findings": [asdict(f) for f in findings]}, indent=2))
    elif args.format == "markdown":
        print(render_markdown(findings, root), end="")
    else:
        print(render_text(findings, root))
    return 1 if findings and args.fail_on_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
