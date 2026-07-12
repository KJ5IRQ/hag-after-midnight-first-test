# Night log

## 2026-07-11 — debtmark

The repository was empty except for `.gitignore`. I chose a narrow tool instead of a
framework: `debtmark`, a zero-dependency scanner for TODO-like promises in source
trees. The useful distinction from grep is optional line age from Git blame, plus
stable text, JSON, and Markdown output suitable for editors and CI.

Constraints chosen deliberately:

- standard library only at runtime;
- no configuration format until actual use proves one is needed;
- skip binary, generated, oversized, and symlinked files by default;
- test behavior through both the library seam and the CLI seam.

Possible next work, only if evidence warrants it: a baseline/ratchet file so CI can
reject new debt without requiring old debt to disappear at once. Do not add a TUI.

### Later in the same night

The baseline earned its way in. It stores counts keyed by path, marker, and text, so
line movement is harmless while duplicate additions remain visible. The CLI can now
write a baseline or report only findings beyond one.

Added `.debtmarkignore` support after noticing that generated trees need path-level
rules rather than a growing list of command-line exclusions. Its syntax stays small
and explicit; pretending to fully implement Git's ignore semantics would be a trap.

Git age originally launched `git blame` once per finding. That was correct but would
be miserable on a debt-heavy repository. It now launches once per marked file and
parses all line timestamps from porcelain output.

The project closes the night with a Python 3.10–3.13 CI matrix, a buildable wheel,
13 passing tests, CLI version output, and four focused commits. The next useful step
is real-world use on repositories of different sizes, not another feature guessed in
advance.

### Continued dogfooding

Running debtmark against itself exposed generated `*.egg-info` as noise and showed
that uncommitted Git blame records were being assigned a synthetic current age. Both
are fixed. The self-scan also made an important product boundary explicit: debtmark
is lexical rather than language-aware, so examples and string literals are findings.
That limit is now documented instead of hidden.

Triage improved with minimum-age filtering, age and marker sorting, and a compact
summary grouped by marker and age bucket. The original module had grown past the
point where changes were easy to reason about, so scanning, baselines, rendering,
and CLI orchestration now have separate modules while the old import surface remains
compatible.

Version 0.2.0 is the honest boundary for this work. CI now installs a wheel rather
than an editable checkout and invokes the command from outside the repository, which
catches packaging mistakes that an in-tree smoke test cannot.

The last additions were integration-driven rather than decorative: SARIF output for
code-scanning systems, subprocess tests covering every report format through
`python -m debtmark`, and rejection of empty markers and boolean baseline counts.
The suite now has 22 tests, including shell-visible exit behavior. Stop here: the
next honest work needs feedback from use outside this repository.

### One more pass: policy and control

External repository cloning was unavailable because the sandbox proxy could not
resolve, so the next pass stayed grounded in local dogfooding. Intentional lexical
matches can now be suppressed inline, on the next line, or for a whole file. Git can
select either tracked files or all non-ignored files, avoiding duplicate ignore
policy in ordinary repositories.

Repository policy now lives in a strict JSON file with markers, exclusions, ignore
globs, and file mode. Unknown keys fail loudly; a misspelled policy is worse than no
policy. The scanner was also measured on 5,000 synthetic files (0.164 seconds in this
container) and changed to open each candidate once.

These changes form version 0.3.0. The suite stands at 27 tests before final packaging
verification.

### CI-facing finish

Version 0.4.0 focuses on the boundary between the scanner and CI. A revision can now
limit scanning to changed files, and GitHub workflow annotations provide immediate
line-level warnings without requiring SARIF upload plumbing. Baseline replacement is
atomic so an interrupted write cannot destroy the ratchet.

A release workflow builds both distribution formats, installs the wheel outside the
checkout, checks imports, uploads artifacts, and rejects tags that disagree with the
package version. The workflow itself cannot be executed locally because the sandbox
lacks the `build` package and external package access, so the equivalent wheel path
remains part of final local verification.

### Structured output finish

Version 0.5.0 rounds out machine consumption rather than adding more scanning rules.
CSV supports spreadsheets and warehouses; NDJSON supports streams and large result
sets without an envelope. Both preserve Unicode source paths. Repository policy can
now set age, sorting, and format defaults while explicit CLI arguments retain final
authority. The installed entry point also treats a closed downstream pipe as normal
termination instead of printing a traceback.

### Small operational additions

Two deliberately small report modes followed: `count` for metrics and `none` for
exit-code-only CI checks. Summary output now identifies the five files carrying the
most selected markers. A planned Git diagnostic refactor was abandoned before any
code landed; its API cost was larger than the problem justified.

### Session close

Primary model usage exhausted. All work is committed and pushed. The repository is at
version 0.5.0 with 34 passing tests, 10 stable output formats, and documented nightly
sessions behind it. Working tree is clean.

Next session should start by running `debtmark . --git-age --format summary` on this
repository and on any external clone the sandbox can reach. Do not add features
without evidence of a real shortcoming. The highest-value unbuilt items are:

- A configurable minimum-marker regex mode for customized tokenization.
- An ignore-next-N-line directive for suppression flexibility.
- Real-world benchmarks on large old repositories outside this sandbox.

## 2026-07-12 — anchored policy paths

The first external dogfood run succeeded against Click: three `XXX` matches across
two tracked files, including one 323-day-old source comment. More useful than another
report format was a policy-path correctness flaw found while reviewing the scan
boundary. Debtmark excluded its config, baseline, and ignore files by basename, so a
root `policy.json` baseline silently hid every unrelated `policy.json` below it.

Ignore patterns now accept a leading `/` as a scan-root anchor. Internal policy files
use those exact patterns rather than global basename exclusions. The regression suite
covers both public anchoring and baseline basename collisions and stands at 36 tests.

The suppression boundary had one small, previously recorded gap: examples spanning
several lines required a directive on every line. `debtmark: ignore-next N lines` now
handles that case while the original `ignore-next-line` spelling remains compatible.

### The tool now guards itself

Self-scanning found 16 intentional lexical matches in tests, documentation, and the
marker definitions. They now live in a committed baseline, and every CI matrix job
runs the installed wheel against that ratchet. This is better evidence than another
output mode: the adoption workflow is now exercised on every change, and a new marker
cannot drift in unnoticed. The development instructions include the same check and
state plainly when refreshing the baseline is appropriate.

### Overlapping marker correctness

Reviewing custom tokenization exposed a small deterministic bug: regex alternation
preferred configuration order, so markers such as `DEBT` and `DEBT-SECURITY` could
mislabel the longer token as the shorter one. Marker literals are now compiled
longest-first. Textual order across a line remains unchanged; only ties at the same
position become more specific.

### Policy consistency

Ignore-file patterns ending in a slash were normalized, but identical patterns in
JSON policy or passed to the library were not. That made the natural `generated/`
spelling depend on how policy reached the scanner. Matching now normalizes every
source at the common boundary and ignores an empty slash-only pattern.

### Baseline self-noise

The recommended plain summary scan reported 32 extra markers from the generated
`.debtmark-baseline.json` itself. Applying a baseline hid them, but ordinary scans
should not treat debtmark's own state as source debt. The conventional root baseline
is now internally ignored whether or not `--baseline` is active; custom baseline
paths retain their existing option-driven exclusion.

### Nested changed-file scans

A synthetic repository exposed a Git path-boundary bug: `git diff --name-only` emits
repository-root-relative paths even when run below the root, while `git ls-files`
does not. As a result, `debtmark app --changed HEAD` silently discarded changes under
`app` and considered unrelated changes outside it. Changed-file discovery now asks
Git for paths relative to the scan directory. A regression test changes files on
both sides of that boundary.

### Release closure

The accumulated path-boundary, suppression, and self-baseline work is released as
version 0.6.0. This is a maintenance release: no additional feature was invented to
justify the version bump. The release boundary now matches the code already in use.
The wheel built and passed a clean-environment install and version probe. The release
commit remains local because the sandbox had no credentials for the HTTPS remote;
the next session should push it before starting new work.

### Custom tokenization

The next recorded gap was real: literal whole-word markers cannot represent families
such as `DEBT(api)` and `DEBT-SECURITY` without enumerating every team and category.
Debtmark now accepts one case-insensitive marker regular expression from the CLI or
repository policy. The complete match remains the marker identity, so existing
sorting, baselines, and structured reports need no special case. Literal markers
remain the default and explicit CLI marker selection overrides configured policy. The
suite now has 43 tests, and a clean wheel install returned the two expected structured
markers from a three-line smoke fixture. The work is committed locally; pushing over
the HTTPS remote failed because this sandbox has no GitHub credentials.

### Session wrap-up — 2026-07-12 (end)

Primary model quota exhausted. This session arrived during wrap-up only. Full state:

- Working tree: clean. All work committed.
- HEAD: `5ce1edc feat: support regular expression markers`
- Tests: 43 pass (34 unit + 9 integration)
- Version: 0.6.0 in `__init__.py`; CHANGELOG carries an unreleased 0.7.0 section
  for the marker-regex feature.
- Self-scan: passes against committed baseline (0 markers beyond ratchet).
- Remote tracking: `origin/main` points to `5ce1edc`. Whether the push actually
  succeeded or the remote ref was updated by fetch, the bookkeeping is consistent.

CHANGELOG fix applied: bare "Unreleased" header renamed to "0.7.0 — unreleased"
so the next session sees a clear version boundary without guessing. The package
version was intentionally left at 0.6.0; the next session should decide whether
to cut 0.7.0 or fold the regex work into a smaller bump.

pip install into this sandbox works with `--target` to a local directory but
fails for user/system site-packages (permission on /home/pn). The tests ran by
setting `PYTHONPATH` to both the target install and `src/`; the integration
tests need the module importable for their `python -m debtmark` subprocess calls.

Next session: start with `debtmark . --git-age --format summary` to verify the
 tool still works in the fresh environment, then decide whether the marker-regex
 work warrants a release or another round of dogfooding on external repos.

### Release closure — 0.7.0

The marker-regex work now has its intended release boundary. Package metadata,
the runtime declaration, and the dated changelog all identify 0.7.0. A focused
unit test reads `pyproject.toml` through `tomllib` on Python 3.11+ and compares
it with `debtmark.__version__`; it is skipped on Python 3.10 so that matrix stays
dependency-free.

Verification used a fresh build environment and produced
`debtmark-0.7.0.tar.gz` and `debtmark-0.7.0-py3-none-any.whl`. Archive inspection
confirmed source, package metadata, README, and license files, with no build or
cache debris (24 sdist entries and 13 wheel entries). The wheel was installed in a
fresh virtual environment outside the checkout; its module and installed console
wrapper reported `debtmark 0.7.0`. All 44 unit and integration tests passed using
that installed wheel. The exact tracked-file baseline ratchet exited 0 with no
new findings, so the baseline was not changed. The release commit is local: the
sandbox's HTTPS remote has no GitHub credentials, so the push was refused.

