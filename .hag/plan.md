# Night build plan — 2026-07-12

The repository is clean at `aaf926a`; 0.6.0 is released and the custom marker-regex work is already committed and documented under an unreleased 0.7.0 heading. The useful work tonight is to close that release cleanly, not invent another feature. The source-backed unit suite passes; integration tests require an installed package by design, as CI already provides.

## 1. Cut and verify debtmark 0.7.0

- [x] Update `pyproject.toml` and `src/debtmark/__init__.py` from 0.6.0 to 0.7.0, and date the existing 0.7.0 section in `CHANGELOG.md`. Do not change marker-regex behavior during the release commit.
- [x] Add a focused version-consistency test in `tests/test_cli.py` that compares `debtmark.__version__` with the project version read from `pyproject.toml` using `tomllib`. This prevents the two currently duplicated version declarations from drifting on later releases; use `tomli` only on Python 3.10 in the test/CI path if necessary, or structure the test so the existing 3.10 matrix remains dependency-light.
- [x] Build both wheel and sdist from a clean tree. Install the wheel into a fresh temporary virtual environment outside the checkout, then verify `debtmark --version` reports 0.7.0 and run the full unit/integration suite with that installed package visible. Inspect the archives to ensure they contain source, package metadata, README, and license but no build/cache debris.
- [x] Run the self-ratchet exactly as CI does: `debtmark . --files tracked --baseline .debtmark-baseline.json --format none --fail-on-findings`. Refresh `.debtmark-baseline.json` only if the version-consistency test introduces an intentional marker match; do not conceal unrelated findings.
- [x] Record the release verification (test count, artifact names, clean-install probe, and self-scan result) in `NIGHTLOG.md`. Commit the release as one coherent commit. Do not create or push a tag: artifact verification is available in the sandbox, but publishing is an operator action.

Expected outcome: source metadata, runtime `--version`, changelog, and built distributions all identify 0.7.0; the regex feature has a finished release boundary and future version drift is caught automatically.

Verification: `python -m unittest discover -s tests -v` succeeds in the fresh wheel environment; both distributions build; the installed CLI prints `debtmark 0.7.0`; archive inspection is clean; the baseline self-check exits 0; and `git status --short` is empty after the release commit.
