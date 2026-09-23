# The orchestrator, advisor and senior advisor in Herdr

Donald assigns three session roles: the **orchestrator** owns execution, the
**advisor** reviews everyday work and explains decisions, and the **senior
advisor** provides second opinions and audits when consulted. The role
boundaries are defined in [AGENTS.md](../AGENTS.md#the-orchestrator-advisor-and-senior-advisor).
Roles are independent of the model or application because two advisor
sessions can use the same application. They are not automatically registered
Herdr agent aliases.

Herdr lets either advisor read the active orchestrator and relay Donald's
authorized instructions into its existing conversation, without copying
prompts between windows or starting another session. Senior review adds no
required approval step.

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
session/socket context. Map each role Donald assigned to its live conversation
ID and pane ID using `herdr agent list` and the session's visible content.
Agent kind and working directory help identify a session, but cannot
distinguish two Codex advisors in the same repository. Do not infer a role
from its model or pane order. If the assignment remains unclear, confirm it
with Donald before sending. `HERDR_PANE_ID` identifies the caller.
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
Submit a prompt only when Donald has authorized that communication. Identify
the sender as advisor or senior advisor and distinguish his instructions from
advice. Either advisor can relay his instructions; the senior title does not
make a recommendation an instruction from Donald.

`agent_prompted` proves submission, not a reply or completed work. Read the
response and verify the requested result. The optional `--wait --timeout 30000`
waits for agent state, not a particular message: a turn already in progress
can satisfy it. After a timeout, read before retrying to avoid duplicate input.

If Herdr reports `agent_blocked`, inspect the dialog. The connection test does
not authorize answering unrelated approvals or overriding a denial. Use
`agent send-keys` only for a specifically authorized interaction. Do not restart
the server, replace the orchestrator, or close its pane to establish access.

## Resume later: host advisor and VM orchestrator

**Plan saved 2026-09-23; not applied or verified end to end.** Keep the
orchestrator in the VM's existing `wish` session and run the advisor on the
desktop, with both visible in one Herdr window. Separate servers remain;
the host advisor reaches the VM through `herdr --machine agent-vm`.

The attempted `machine add` failed because strict SSH checking found no
trusted ED25519 host key. The project's
`ansible/roles/agent-vm/templates/agent-vm-ssh-config.j2` disables checking and
sets `UserKnownHostsFile /dev/null`, so ordinary connections do not retain a
key. Saving a key alone will not fix that configuration.

1. **Fix host-key storage on the desktop.** Inspect `ssh -G agent-vm`.
   Add a `Host agent-vm` block at the beginning of the desktop user's
   `~/.ssh/config` with `UserKnownHostsFile ~/.ssh/known_hosts` and
   `StrictHostKeyChecking yes`. Preserve the existing host, user and identity
   settings supplied by the system configuration. Confirm the effective
   settings with `ssh -G agent-vm` again.
2. **Verify and enroll the VM's key.** In the VM console or existing trusted
   session, run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. On the
   desktop, run `ssh -o StrictHostKeyChecking=ask agent-vm true`; accept only
   if the fingerprint matches. Then confirm `ssh agent-vm true` succeeds.
   Do not bypass checking or blindly accept a changed key.
3. **Connect both machines in one interface.** From a desktop terminal:

   ```sh
   herdr machine add agent-vm --label agent-vm --remote-session wish
   herdr
   ```

   Keep the existing remote session running. If setup proposes replacing its
   server and stopping panes, decline and resolve compatibility separately.
4. **Start the advisor under Local.** Use a host checkout with the current
   `AGENTS.md`. Verify cross-machine access with
   `herdr --machine agent-vm agent list`, discover the orchestrator's live
   pane, then read it with `herdr --machine agent-vm agent read <pane-id>
   --source visible`. No test message is needed.
5. **Define the host operator role before applying Ansible.** The advisor
   still answers questions without forwarding them. Document an explicit
   exception allowing host Ansible runs when Donald requests them; routine
   application implementation remains with the VM orchestrator. Use the
   desktop's inventory and credentials, with scoped execution permissions.

For a durable project fix, update the Ansible SSH template to retain verified
host keys and specify how a rebuilt VM's replacement key is verified. That
implementation is deferred; saving this plan authorizes no deployment.

## Verified connection

This two-session test predates the senior advisor role. It does not establish
a current three-session mapping; discover the live sessions before use.

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
