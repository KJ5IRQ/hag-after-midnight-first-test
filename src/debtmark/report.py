"""Human-readable and machine-readable report rendering."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Sequence

from .core import Finding


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


def render_summary(findings: Sequence[Finding], root: Path) -> str:
    """Render repository-level counts for quick triage."""
    file_count = len({finding.path for finding in findings})
    lines = [f"debtmark: {len(findings)} marker(s) across {file_count} file(s) in {root}"]
    if not findings:
        return "\n".join(lines)

    marker_counts = Counter(finding.marker for finding in findings)
    lines.append("markers:")
    width = max(len(marker) for marker in marker_counts)
    for marker, count in sorted(marker_counts.items()):
        lines.append(f"  {marker:<{width}}  {count}")

    age_counts = {"<30d": 0, "30-89d": 0, "90-364d": 0, ">=365d": 0, "unknown": 0}
    for finding in findings:
        if finding.age_days is None:
            age_counts["unknown"] += 1
        elif finding.age_days < 30:
            age_counts["<30d"] += 1
        elif finding.age_days < 90:
            age_counts["30-89d"] += 1
        elif finding.age_days < 365:
            age_counts["90-364d"] += 1
        else:
            age_counts[">=365d"] += 1
    if any(count for label, count in age_counts.items() if label != "unknown"):
        lines.append("ages:")
        for label, count in age_counts.items():
            if count:
                lines.append(f"  {label:<7}  {count}")
    return "\n".join(lines)
