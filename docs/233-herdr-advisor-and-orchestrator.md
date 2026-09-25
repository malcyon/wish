# The orchestrator, advisor and senior advisor in Herdr

Donald assigns three session roles. The **Wish orchestrator** owns application
work; the **host advisor** answers independently and owns authorized host and
VM maintenance, including Ansible and sshfs; the **senior advisor** gives
second opinions when consulted. [AGENTS.md](../AGENTS.md#the-orchestrator-advisor-and-senior-advisor)
defines their boundaries. Roles are independent of model, application and
Herdr's agent aliases.

Herdr lets an advisor inspect the orchestrator and relay Donald's authorized
Wish application handoffs. Host and VM maintenance stays with the advisor;
neither its requests nor its progress goes to the Wish orchestrator. Senior
review adds no required approval step.

## Everyday launch after setup

On the desktop, run `herdr`. Use **Local** in the sidebar for the host advisor
and the saved **agent-vm / wish** machine and session for the existing remote
orchestrator. The VM's session stays running. Adding the machine and verifying
its SSH host key are one-time setup steps below, not part of each launch. The
host arrangement is planned and has not been verified end to end.

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

Stop if the environment check fails. Bare commands use the caller's Herdr
server. From the host advisor, every VM discovery, read or prompt needs the
saved machine prefix: `herdr --machine agent-vm agent list`,
`herdr --machine agent-vm agent read ...`, or
`herdr --machine agent-vm agent prompt ...`. Map each role to its live
conversation ID and pane ID using the appropriate agent list and visible
content.
Agent kind and working directory help identify a session, but cannot
distinguish two Codex advisors in the same repository. Do not infer a role
from its model or pane order. If the assignment remains unclear, confirm it
with Donald before sending. `HERDR_PANE_ID` identifies the caller.
Pane IDs and agent names belong to one server. Discover them again after a
restart or move rather than assuming the IDs below still apply.

Codex's default command sandbox can show root-owned host SSH files as owned by
`nobody:nogroup`. If `herdr --machine agent-vm agent list` fails with
`Bad owner or permissions on /etc/ssh/ssh_config.d/agent-vm.conf`, verify the
host view before changing SSH configuration. Run a read-only `stat` of that
file and repeat the Herdr read through approved `require_escalated` execution.
On 2026-09-24, the sandbox showed `nobody:nogroup`, while the host view showed
`root:root` and the Herdr read succeeded. This error occurs before SSH
authentication; if it persists outside the sandbox, investigate actual host
file ownership.

The bare commands below ran on the same server in the connection test. The
historical pane ID is an example; discover the live target before use:

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

**The one-time connection plan was saved 2026-09-23 and has not been applied
or verified end to end.** Keep the orchestrator in the VM's existing `wish`
session and run the advisor on the desktop, with both visible in one Herdr
window. Separate servers remain;
the host advisor reaches the VM through `herdr --machine agent-vm` for CLI
commands.

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
3. **Save the VM as a machine.** From a desktop terminal:

   ```sh
   herdr machine add agent-vm --label agent-vm --remote-session wish
   ```

   Keep the existing remote session running. If setup proposes replacing its
   server and stopping panes, decline and resolve compatibility separately.
4. **Start the advisor under Local.** Run `herdr` on the desktop. Use a host
   checkout with the current `AGENTS.md`. Verify cross-machine access with
   `herdr --machine agent-vm agent list`, discover the orchestrator's live
   pane, then read it with `herdr --machine agent-vm agent read <pane-id>
   --source visible`. No test message is needed.

The host advisor role is now defined in `AGENTS.md`: Donald assigned VM
maintenance to that role, so the earlier pending role decision is resolved.
For requested maintenance, use the desktop's inventory and credentials with
scoped execution permissions. An advisory question alone does not authorize
an Ansible run.

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

## Emulator audio on the two guests

Host inspection on 2026-09-24 with `virsh dumpxml agent-vm` found no
`sound` device and an `audio` backend of `none`. VICE's headless launcher
disables sound, and the pooled DOSBox configuration disables the mixer,
Sound Blaster and PC speaker. This configuration establishes silence for
those guest runs; the missing guest PulseAudio tools and sockets are not a
reason to stop them. The guidance was corrected because requiring a guest
sink query had stopped experiments before they claimed an emulator slot,
despite there being no virtual audio path. Recheck the live configuration
after audio or VM changes rather than treating this observation as permanent.

The separate `win11` guest has an ICH9 sound device and SPICE audio forwarding.
Its WinUAE runs still need Windows playback mute readback; the Linux guest's
silence evidence does not apply to it. Keep WinUAE's sound interrupts enabled
and follow [the emulator rule](../.claude/rules/emulator.md).

## References

The installed `herdr --skill` and command help govern the installed version.
The upstream [agent automation guide](https://herdr.dev/docs/agent-automation/)
and [socket API reference](https://herdr.dev/docs/socket-api/) explain the
control surface and message-wait limitations.
