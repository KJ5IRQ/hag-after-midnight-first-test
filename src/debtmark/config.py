"""Repository policy configuration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Config:
    markers: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    files: str | None = None


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
    allowed = {"markers", "exclude", "ignore", "files"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown config field: {unknown[0]}")
    files = payload.get("files")
    if files is not None and files not in {"all", "git", "tracked"}:
        raise ValueError("config files must be all, git, or tracked")
    return Config(
        markers=_string_list(payload, "markers", nonempty=True),
        excludes=_string_list(payload, "exclude", nonempty=True),
        ignore=_string_list(payload, "ignore", nonempty=True),
        files=files,
    )
