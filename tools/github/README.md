# github

Scripts that read GitHub issues so that a stranger's text is withheld: the trust check and the issue reader.

| file | purpose |
|---|---|
| `ghtrust.py` | Says who is trusted on the public issue tracker (`malcyon` and `wish-agent[bot]`, everyone else outside) and holds the flattening and `withheld(...)` sentence `issueread.py` and `.claude/hooks/issue-titles-context.py` share; standard library only, because the hook imports it under the system `python3`. |
| `issueread.py` | Prints one issue in full for a trusted author and withholds an outsider's title, body or comment text, naming the author, length and command that shows it; `--json` for scripts; shells out to `gh` and fails loudly. |
