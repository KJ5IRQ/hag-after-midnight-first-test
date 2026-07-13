# Night build plan

Debtmark is released at 0.7.8 and its 50-test suite is healthy when exercised through the installed-package path used by CI. The strict `--changed` revision correction and its release work below are complete. The successor `artifact-audit` project request has been fulfilled, but this checkout is still the debtmark repository. It is in maintenance mode: do not invent another report format or broaden the scanner without a reproduced shortcoming.

## 1. Treat `--changed` revisions strictly as revisions

- [x] In `src/debtmark/core.py`, harden `git_changed_files()` so an option-like value can never be interpreted as a `git diff` flag. Prefer Git's end-of-options boundary if it works across the supported Git command shape; otherwise resolve the user value first with a separate option-safe `git rev-parse --verify` call and pass only the resulting object ID to `git diff`. Preserve the existing behavior for branches, tags, commit IDs, nested scan roots, staged changes, unstaged changes, renames, and NUL-delimited unusual paths.
- [x] Add focused regressions in `tests/test_cli.py`: a normal `HEAD` revision must still select changed files; an option-like value such as `--cached` must return `None` from `git_changed_files()` rather than alter diff mode; and the CLI must turn that failure into exit status 2 with the existing `cannot resolve changed files` diagnostic. Keep the test repository local and deterministic.
- [x] Run the complete suite through an installed package, not merely `PYTHONPATH`: install the checkout into a fresh temporary virtual environment outside `/workspace`, then run `python -m unittest discover -s tests -v`. Also run the exact self-ratchet command from `.github/workflows/test.yml` and confirm it exits 0 without refreshing `.debtmark-baseline.json` unless the new test contains an intentional marker literal.

Expected outcome: `--changed` accepts only a revision operand; Git options cannot masquerade as revisions, while ordinary and nested-root changed-file scans behave exactly as before.

Verification: the new library and CLI regressions pass; all existing tests pass from the fresh install; `debtmark TMP --changed=--cached` exits 2 in a synthetic repository; `debtmark TMP --changed HEAD` still reports the expected changed file; and the baseline ratchet exits 0.

## 2. Release the correction as 0.7.8

- [x] Update `pyproject.toml`, `src/debtmark/__init__.py`, and `CHANGELOG.md` to 0.7.8 with a concise security/correctness-facing note that option-like changed revisions are rejected rather than interpreted by Git. Do not bundle unrelated behavior.
- [x] Build wheel and sdist, install the wheel into a second clean external virtual environment, verify both `debtmark --version` and the full suite against that wheel, and inspect the archives for the expected source, metadata, README, and license without cache/build debris.
- [x] Record the reproduction, fix strategy, test count, artifact names, clean-install probe, and ratchet result in `NIGHTLOG.md`. Commit the release. Do not tag or publish; those remain operator actions.

Expected outcome: the repository has a narrow, verified 0.7.8 patch release and then returns to maintenance mode rather than accumulating speculative features.

Verification: source metadata, runtime version, changelog, wheel, and sdist all identify 0.7.8; the installed-wheel suite and self-ratchet pass; `git diff --check` is clean; and `git status --short` is empty after the release commit.
