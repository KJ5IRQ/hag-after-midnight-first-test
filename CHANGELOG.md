# Changelog

All notable changes are recorded here. The project follows Semantic Versioning.

## 0.7.8 — 2026-07-13

### Fixed

- Changed-file revisions that resemble Git options are rejected rather than being
  interpreted as `git diff` flags.

## 0.7.7 — 2026-07-12

### Fixed

- Age-enabled scans outside Git work trees no longer launch one failed blame process
  for every marked file.

## 0.7.6 — 2026-07-12

### Fixed

- Git ages are now unknown in shallow clones instead of being misleadingly
  attributed to the clone boundary commit.

## 0.7.5 — 2026-07-12

### Fixed

- SARIF artifact locations now percent-encode special and Unicode path characters.

## 0.7.4 — 2026-07-12

### Fixed

- Markdown reports preserve table structure and faithfully display pipes in paths
  and custom markers.

## 0.7.3 — 2026-07-12

### Fixed

- Markdown reports now escape table separators in file paths and custom markers.

## 0.7.2 — 2026-07-12

### Fixed

- Empty NDJSON scans no longer emit a blank line, which is not an NDJSON record.

## 0.7.1 — 2026-07-12

### Changed

- Modernized package license metadata to PEP 639 syntax and require a compatible
  setuptools build backend, removing its deprecated-license build warning.

## 0.7.0 — 2026-07-12

### Added

- Case-insensitive custom marker regular expressions through `--marker-regex` and
  the `marker_regex` policy field.

## 0.6.0 — 2026-07-12

### Added

- Count-only and silent report modes for shell and CI checks.
- Top-five file concentration in summary reports.
- Root-anchored ignore patterns using a leading slash.
- Multi-line suppression with `debtmark: ignore-next N lines`.

### Fixed

- Policy files no longer exclude unrelated files with the same basename elsewhere
  in the scanned tree.
- Overlapping custom markers now report the longest matching literal regardless of
  configuration order.
- Ignore patterns supplied by configuration or the library now accept trailing
  slashes consistently with patterns read from ignore files.
- The conventional root baseline is no longer reported as debt during ordinary
  scans that do not pass `--baseline`.
- Changed-file scans started below a repository root now use paths relative to the
  requested scan root and do not silently omit in-scope changes.

## 0.5.0 — 2026-07-11

### Added

- CSV output with stable columns and newline-delimited JSON output.
- Repository policy defaults for minimum age, sorting, and report format.

### Changed

- Explicit CLI triage and report options override repository policy defaults.
- Console entry points handle closed downstream pipes without a traceback.
- Structured formats preserve Unicode paths and text.

## 0.4.0 — 2026-07-11

### Added

- Changed-file scanning relative to a Git revision.
- GitHub Actions warning annotations with workflow-command escaping.
- Tag and manual workflows for building and verifying release artifacts.

### Changed

- Baseline writes are atomic, durable, and preserve existing permissions.

## 0.3.0 — 2026-07-11

### Added

- Inline, next-line, and whole-file suppression directives.
- Git-aware selection of tracked or non-ignored files.
- Strict repository policy files through `.debtmark-config.json` or `--config`.

### Changed

- Candidate files are opened once instead of separately for binary detection and
  text scanning.
- CLI integration coverage now includes configuration and Git work-tree failures.

## 0.2.0 — 2026-07-11

### Added

- Baseline files for rejecting only newly introduced debt.
- `.debtmarkignore` glob files.
- Minimum-age filtering and path, marker, or age sorting.
- Compact summaries grouped by marker and age bucket.
- SARIF 2.1.0 output for code-scanning integrations.
- JSON and Markdown report formats.
- Python 3.10–3.13 continuous integration.

### Changed

- Git blame runs once per marked file rather than once per finding.
- Scanning, baseline persistence, and report rendering are separate library modules.
- Generated Python metadata and common tool caches are skipped by default.
- Uncommitted blame records correctly report unknown age.
- Empty custom markers and malformed baseline counts are rejected.

## 0.1.0 — 2026-07-11

- Initial zero-dependency scanner with text output and optional Git age.
