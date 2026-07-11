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
$ debtmark . --format json
$ debtmark . --format markdown > debt-report.md
$ debtmark . --marker NOTE --marker DEPRECATED
$ debtmark . --exclude fixtures --fail-on-findings
```

Text output is deliberately compatible with editor “file:line” navigation:

```text
debtmark: 2 marker(s) in /work/project
src/cache.py:41: FIXME [327d]  # FIXME: this races during eviction
src/http.py:9: HACK [12d]  # HACK: remove after the upstream release
```

`--fail-on-findings` exits with status 1 if anything is found, making the command
usable as a CI ratchet. Invalid paths exit with status 2. Without that flag, a
successful scan exits with status 0 regardless of findings.

## Design limits

- Markers are whole words and case-insensitive.
- A line containing several markers is reported once, under the first marker.
- Git age uses the author timestamp from `git blame`; uncommitted lines have no age.
- Exclusions match file or directory names, not globs.

## Development

```console
python -m unittest discover -s tests -v
```
