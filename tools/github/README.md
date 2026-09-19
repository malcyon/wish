# github

Scripts that read GitHub issues so that a stranger's text is withheld: the trust check and the issue reader.

| file | purpose |
|---|---|
| `ghtrust.py` | Who is trusted on `malcyon/wish`'s public issue tracker -- `malcyon` and `wish-agent[bot]`, everyone else an outside account -- plus the flattening and the one `withheld(...)` sentence both `.claude/hooks/issue-titles-context.py` and `issueread.py` build on. Standard library only, since the hook imports it under whatever `python3` is on `PATH` rather than under `.venv`. |
| `issueread.py` | Reads one issue the way an agent should before working it -- `gh issue view N --comments` prints every comment's body verbatim, and the repository is public with issues enabled, so a comment's author can be anyone. `issueread.py N` prints the issue in full for a trusted author (`malcyon`, `wish-agent[bot]`) and, for anyone else, withholds the title, body or comment text through `ghtrust.py`'s `withheld(...)` -- naming the author, the length, and the exact command or URL that would show it, never the text itself. `--json` prints the same information structured for a script. Withheld, not dropped: a summary line at the top says how many comments came from outside accounts and from whom, so an agent can still tell Donald there is something to look at. Shells out to `gh`, already authenticated as Donald; fails loudly, unlike the session-start hook it shares `ghtrust.py` with. |
