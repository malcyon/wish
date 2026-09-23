# hooks

Tests for the scripts under `.claude/hooks/`: what each one refuses and what it lets through.

| file | purpose |
|---|---|
| `test_check_issue_reads.py` | Checks that `check-issue-reads.py` refuses every form of `gh` read that would print an outside author's comment text and lets the ordinary reads through. |
| `test_check_issue_writes.py` | Checks that `check-issue-writes.py` refuses a `gh` write that would go out under the maintainer's name and lets reads and repository commands through. |
| `test_check_orchestrator_edits.py` | Checks that `check-orchestrator-edits.py` refuses an edit made by the orchestrating main window and lets subagents and other sessions edit. |
| `test_issue_titles_context.py` | Checks that `issue-titles-context.py` prints a trusted author's issue title in full and withholds an outside author's. |
| `test_notify_context_size.py` | Checks that `notify-context-size.py` sums a session's context from its token counts and prints its one notice only once the context passes the line. |
| `test_retired_push_hook.py` | Checks that `check-push-tested.py`, a retired entry point kept so a session with cached hook wiring does not fail, lets every command through and is registered in neither the Claude Code nor the Codex wiring. |
