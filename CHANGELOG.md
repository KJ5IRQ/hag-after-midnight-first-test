# Changelog

All notable changes are recorded here. The project follows Semantic Versioning.

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
