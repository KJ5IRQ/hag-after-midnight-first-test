"""Baseline persistence and comparison."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from .core import Finding

BASELINE_VERSION = 1
FindingKey = tuple[str, str, str]


def _finding_key(finding: Finding) -> FindingKey:
    return finding.path, finding.marker, finding.text


def write_baseline(path: Path, findings: Sequence[Finding]) -> None:
    """Write stable finding identities and counts, deliberately omitting line numbers."""
    counts = Counter(_finding_key(finding) for finding in findings)
    entries = [
        {"path": key[0], "marker": key[1], "text": key[2], "count": count}
        for key, count in sorted(counts.items())
    ]
    content = json.dumps({"version": BASELINE_VERSION, "findings": entries}, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        mode = path.stat().st_mode if path.exists() else 0o644
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_baseline(path: Path) -> Counter[FindingKey]:
    """Read and validate a baseline file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version (expected {BASELINE_VERSION})")
    entries = payload.get("findings")
    if not isinstance(entries, list):
        raise ValueError("baseline findings must be a list")
    counts: Counter[FindingKey] = Counter()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("baseline finding must be an object")
        try:
            key = (entry["path"], entry["marker"], entry["text"])
            count = entry["count"]
        except KeyError as error:
            raise ValueError(f"baseline finding lacks {error.args[0]}") from error
        if (
            not all(isinstance(value, str) for value in key)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
        ):
            raise ValueError("baseline finding has invalid values")
        counts[key] += count
    return counts


def new_since_baseline(findings: Sequence[Finding], baseline: Counter[FindingKey]) -> list[Finding]:
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
