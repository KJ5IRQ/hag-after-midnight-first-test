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
