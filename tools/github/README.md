# github

Scripts for trusted issue reads and exact-commit CI checks.

| file | purpose |
|---|---|
| `ghtrust.py` | Says who is trusted on the public issue tracker (`malcyon` and `wish-agent[bot]`, everyone else outside) and holds the flattening and `withheld(...)` sentence `issueread.py` and `.claude/hooks/issue-titles-context.py` share; standard library only, because the hook imports it under the system `python3`. |
| `issueread.py` | Prints one issue in full for a trusted author and withholds an outsider's title, body or comment text, naming the author, length and command that shows it; `--json` for scripts; shells out to `gh` and fails loudly. |
| `ciwatch.py` | Waits within a fixed deadline for both required push workflows and their jobs to succeed on one exact commit SHA, then prints a compact JSON result. |
