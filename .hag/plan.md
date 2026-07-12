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

## 2. Exercise the distribution in release CI

- [x] Extend `.github/workflows/release.yml` so its fresh wheel environment runs the complete unit and integration suite, not merely an import smoke test. Keep the test interpreter outside the checkout and leave artifact publication unchanged.
- [x] Validate the workflow YAML and reproduce the installed-wheel test command locally. Record the result in `NIGHTLOG.md`, commit, and push.

## 3. Remove the package-build deprecation warning

- [x] Move the project license declaration to PEP 639 syntax, require the setuptools version that supports it, and release the metadata-only correction as 0.7.1.
- [x] Build both artifacts without the deprecated-license warning; inspect wheel metadata for the SPDX expression and packaged license; install the wheel outside the checkout and run the full suite plus the baseline check. Record, commit, and push.

## 4. Correct empty NDJSON output

- [x] Make `--format ndjson` emit zero bytes when a scan has no findings rather than a blank non-JSON line. Add focused CLI coverage, release the behavior fix as 0.7.2, and verify a clean wheel install.

## 5. Preserve Markdown table structure for arbitrary markers and paths

- [x] Escape table separators in Markdown location and marker cells, not only finding text. Add regression coverage, release 0.7.3, and verify the installed artifact.
