# The advisor and orchestrator in Herdr

Donald uses the **advisor** (Codex) to review work and explain decisions, and
the **orchestrator** (Claude Code) to run the issue queue and coordinate its
workers. Herdr lets the advisor read the active orchestrator and send Donald's
authorized instructions into the same conversation, without copying prompts
between windows or starting another Claude session. These are role names;
they are not automatically registered Herdr agent aliases.

## Connect to the existing conversation

Use Herdr's CLI and socket API directly. No tmux MCP server is needed; Herdr
owns these terminals. Read the installed skill and help before control:

```sh
herdr --skill
test "${HERDR_ENV:-}" = 1
herdr --help
herdr agent --help
herdr status
herdr agent list
```

Stop if the environment check fails. Within Herdr, commands use the inherited
session/socket context. Match the returned agent kind, working directory and
conversation ID to the intended session; `HERDR_PANE_ID` identifies the caller.
Pane IDs and agent names belong to one server. Discover them again after a
restart or move rather than assuming the IDs below still apply.

The following commands use the orchestrator pane found in the connection test:

```sh
herdr agent read w1:p1 --source visible
herdr agent prompt w1:p1 'Reply with your current status.'
herdr agent read w1:p1 --source visible
```

Read before sending. Use `--source visible` for a passive view of an active
agent; a larger recent-history read can scroll an idle agent's application.
Submit a prompt only when Donald has authorized that communication. Include
that it comes from the advisor and distinguish his instructions from advice.

`agent_prompted` proves submission, not a reply or completed work. Read the
response and verify the requested result. The optional `--wait --timeout 30000`
waits for agent state, not a particular message: a turn already in progress
can satisfy it. After a timeout, read before retrying to avoid duplicate input.

If Herdr reports `agent_blocked`, inspect the dialog. The connection test does
not authorize answering unrelated approvals or overriding a denial. Use
`agent send-keys` only for a specifically authorized interaction. Do not restart
the server, replace the orchestrator, or close its pane to establish access.

## Verified connection

On 2026-09-22, both the client and server were Herdr 0.9.1, protocol 22, with
compatible endpoints and no restart required. The test used the `wish` session.

| Role | Agent | Pane at test time | Conversation ID |
|---|---|---|---|
| Orchestrator | Claude Code | `w1:p1` | `e02ad860-99ec-46f6-89cb-48689d484b40` |
| Advisor | Codex | `w1:p3` | `01a0caf5-0f1c-77b2-95f6-f63f464c8fc7` |

The advisor discovered both agents, read the orchestrator's visible terminal,
and submitted a connection-only prompt asking for
`ADVISOR_ORCHESTRATOR_LINK_OK_20260922`. A subsequent visible read showed that
exact token as Claude's reply, followed by its existing wait for workers.
This verified discovery, reading, submission and acknowledgment. Interruption,
approval responses, role aliases and automatic monitoring were not tested.

The sandboxed discovery command failed with `PermissionDenied` / `Operation
not permitted`. The same command succeeded through approved execution outside
the sandbox. Reads, status and the test prompt used that approved route too.
This was a local socket access restriction, not evidence that Herdr was down.
Request the required tool approval when socket access is denied; do not try to
bypass the sandbox or broaden permissions silently.

## References

The installed `herdr --skill` and command help govern the installed version.
The upstream [agent automation guide](https://herdr.dev/docs/agent-automation/)
and [socket API reference](https://herdr.dev/docs/socket-api/) explain the
control surface and message-wait limitations.
