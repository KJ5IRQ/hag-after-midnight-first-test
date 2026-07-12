"""Repository policy configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Config:
    markers: tuple[str, ...] = ()
    marker_regex: str | None = None
    excludes: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    files: str | None = None
    min_age: int | None = None
    sort: str | None = None
    format: str | None = None


def _string_list(payload: dict[str, object], key: str, *, nonempty: bool = False) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"config {key} must be a list of strings")
    if nonempty and any(not item.strip() for item in value):
        raise ValueError(f"config {key} entries must not be empty")
    return tuple(value)


def read_config(path: Path) -> Config:
    """Read and strictly validate a debtmark JSON policy file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config must be an object")
    allowed = {
        "markers", "marker_regex", "exclude", "ignore", "files", "min_age", "sort", "format"
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown config field: {unknown[0]}")
    marker_regex = payload.get("marker_regex")
    if marker_regex is not None:
        if not isinstance(marker_regex, str) or not marker_regex:
            raise ValueError("config marker_regex must be a non-empty string")
        if payload.get("markers"):
            raise ValueError("config markers and marker_regex are mutually exclusive")
        try:
            compiled_marker_regex = re.compile(marker_regex, re.IGNORECASE)
        except re.error as error:
            raise ValueError(f"config marker_regex is invalid: {error}") from error
        if compiled_marker_regex.match("") is not None:
            raise ValueError("config marker_regex must not match empty text")
    files = payload.get("files")
    if files is not None and files not in {"all", "git", "tracked"}:
        raise ValueError("config files must be all, git, or tracked")
    min_age = payload.get("min_age")
    if min_age is not None and (
        not isinstance(min_age, int) or isinstance(min_age, bool) or min_age < 0
    ):
        raise ValueError("config min_age must be a non-negative integer")
    sort = payload.get("sort")
    if sort is not None and sort not in {"path", "age", "marker"}:
        raise ValueError("config sort must be path, age, or marker")
    output_format = payload.get("format")
    formats = {
        "text", "count", "none", "json", "ndjson", "csv",
        "markdown", "summary", "sarif", "github",
    }
    if output_format is not None and output_format not in formats:
        raise ValueError("config format is invalid")
    return Config(
        markers=_string_list(payload, "markers", nonempty=True),
        marker_regex=marker_regex,
        excludes=_string_list(payload, "exclude", nonempty=True),
        ignore=_string_list(payload, "ignore", nonempty=True),
        files=files,
        min_age=min_age,
        sort=sort,
        format=output_format,
    )
