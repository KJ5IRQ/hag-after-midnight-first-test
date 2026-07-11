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
