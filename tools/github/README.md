# github

Scripts for trusted issue reads and exact-commit CI checks.

| file | purpose |
|---|---|
| `ciwatch.py` | Monitors both required push workflows for one exact commit SHA, reports each completed failed job once while other jobs finish, and prints a bounded final JSON result. Routine runs require four shards per platform; `--shard-count 2` checks workflows that retain the route job with two shards. |
| `ghtrust.py` | Says who is trusted on the public issue tracker (`malcyon` and `wish-agent[bot]`, everyone else outside) and holds the flattening and `withheld(...)` sentence `issueread.py` and `.claude/hooks/issue-titles-context.py` share; standard library only, because the hook imports it under the system `python3`. |
| `issueread.py` | Prints one issue in full for a trusted author and withholds an outsider's title, body or comment text, naming the author, length and command that shows it; `--json` for scripts; shells out to `gh` and fails loudly. |
