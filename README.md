# debtmark

Codebases accumulate promises in comments. `debtmark` makes those promises visible:
where they are, what kind they are, and—when Git knows—how long they have sat there.

It is a zero-dependency Python CLI. It skips common generated directories, binary
files, symlinks, and files larger than 2 MiB.

## Install

```console
python -m pip install -e .
```

Python 3.10 or newer is required.

## Use

```console
$ debtmark src
$ debtmark . --git-age
$ debtmark . --min-age 180 --sort age
$ debtmark . --format json
$ debtmark . --format ndjson
$ debtmark . --format csv > debt.csv
$ debtmark . --format markdown > debt-report.md
$ debtmark . --git-age --format summary
$ debtmark . --format sarif > debtmark.sarif
$ debtmark . --marker NOTE --marker DEPRECATED
$ debtmark . --exclude fixtures --fail-on-findings
$ debtmark . --write-baseline .debtmark-baseline.json
$ debtmark . --baseline .debtmark-baseline.json --fail-on-findings
$ debtmark . --ignore-file tools/debtmark.ignore
$ debtmark . --files git
$ debtmark . --files tracked
$ debtmark . --config tools/debtmark.json
$ debtmark . --changed origin/main --fail-on-findings
$ debtmark . --format github
```

Text output is deliberately compatible with editor “file:line” navigation:

```text
debtmark: 2 marker(s) in /work/project
src/cache.py:41: FIXME [327d]  # FIXME: this races during eviction
src/http.py:9: HACK [12d]  # HACK: remove after the upstream release
```

`--fail-on-findings` exits with status 1 if anything is found. Invalid paths exit
with status 2. Without that flag, a
successful scan exits with status 0 regardless of findings.

JSON wraps findings with the absolute scan root and count. NDJSON emits one finding
object per line for streaming pipelines. CSV has a stable header and column order.
Markdown is suitable for reports, summary is for quick triage, SARIF targets code
scanning systems, and GitHub format emits workflow annotations.

## Adopt it without cleaning everything first

Capture the current debt, commit the baseline, then fail CI only when a change adds
more:

```console
debtmark . --write-baseline .debtmark-baseline.json
debtmark . --baseline .debtmark-baseline.json --fail-on-findings
```

Baseline identities use path, marker, and comment text—not line number—so ordinary
line movement does not create false positives. Duplicate comments are counted, so a
third copy is still new. The baseline file itself is excluded when it sits below the
scanned root.

## Ignore generated or vendored paths

If `.debtmarkignore` exists at the scan root, it is loaded automatically. Blank lines
and lines beginning with `#` are ignored. Patterns without a slash match any path
component; patterns with a slash match paths relative to the scan root.

```text
# generated trees
vendor
fixtures/snapshots
src/*.generated.py
```

This is intentionally a small glob format, not a clone of `.gitignore`: negation and
escaped comments are not supported. Use `--ignore-file PATH` to select another file.

In a Git work tree, `--files git` scans tracked files plus untracked files not ignored
by Git. `--files tracked` scans only files in the index. Both modes still apply
debtmark's built-in exclusions and `.debtmarkignore` rules.

## Suppress intentional matches

Keep exceptions beside the code when excluding an entire path would be too broad:

```python
compatibility = "TODO"  # debtmark: ignore
# debtmark: ignore-next-line
example = "FIXME: shown in documentation"
```

Put `debtmark: ignore-file` anywhere in a file to suppress that file completely.
Directives are case-insensitive and lexical, like marker scanning itself.

## Repository policy

Debtmark automatically reads `.debtmark-config.json` from the scan root. A different
file can be selected with `--config`. Command-line markers and file mode override the
configured values; command-line exclusions are added to configured exclusions.

```json
{
  "markers": ["TODO", "FIXME", "DEPRECATED"],
  "exclude": ["fixtures"],
  "ignore": ["docs/examples/**"],
  "files": "git",
  "min_age": 30,
  "sort": "age",
  "format": "summary"
}
```

Unknown fields and malformed values are errors rather than silently ignored policy.
Explicit command-line marker, file, age, sort, and format options override configured
defaults.

For pull-request checks, `--changed REVISION` restricts scanning to files added,
copied, modified, or renamed relative to that Git revision. Untracked files are not
part of a revision diff. An explicit `--changed` overrides configured file mode and
cannot be combined with an explicit `--files` option.

## Design limits

- Markers are whole words and case-insensitive.
- Scanning is lexical, not language-aware: marker text in strings and documentation
  is reported. Exclude such paths or capture them in a baseline when intentional.
- A line containing several markers is reported once, under the first marker.
- Git age uses the author timestamp from `git blame`; uncommitted lines have no age.
- `--min-age` excludes uncommitted markers because they have no meaningful age.
- Exclusions match file or directory names, not globs.
- Ignore-file patterns use case-sensitive shell globs.

## Development

```console
python -m unittest discover -s tests -v
```
