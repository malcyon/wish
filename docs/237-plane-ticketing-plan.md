# Plane ticket tracking on the media server

Donald and the agents need one ticket queue available from the LAN and from
`agent-vm`. Deploy Plane at `https://plane.morton.lan`, with service and backup
IaC in `/home/donald/src/jellyfin-stack` and VM access IaC in
`/home/donald/src/wish`. This plan uses repository inspection and vendor
documentation checked on 2026-10-02. Deployment, live migration and activation
of the proposed rules remain implementation work.

## Recommended design

| Component | Plan | Evidence or constraint |
|---|---|---|
| Edition | Community Edition, pinned to a tested release and image digests. | The [edition guide](https://developers.plane.so/self-hosting/editions-and-versions) identifies Community as AGPL. Verify required ticket operations against the chosen release before migration. |
| Host | A separate Compose project on media-server, currently `192.168.1.182`. | `jellyfin-stack/ansible/inventory.yml` and `ansible/group_vars/media_servers/vars.yml`. |
| Ingress | Existing Nginx Proxy Manager (NPM), forwarding HTTPS to a Plane routing container. | Main Compose already assigns NPM ports 80, 81 and 443. |
| DNS | An Ansible-managed Pi-hole record for `plane.morton.lan`. | The media role already preserves and extends Pi-hole `dns.hosts` for Grafana. |
| Agents | Plane's official local MCP implementation behind a Wish policy adapter, configured in both clients. | Local stdio supports a private instance; ticket text still needs Wish's filtering. |
| Backup | A daily media-server systemd job creates an encrypted restic snapshot in OneDrive. | Proposed configurable destination: `Backups/Plane/media-server`. |
| Work register | Switch to Plane only after infrastructure, restore, client and migration acceptance. | GitHub continues hosting code, pull requests, CI and public intake. |

The supplied [self-hosting overview](https://developers.plane.so/self-hosting/overview)
is the entry point. The [Compose guide](https://developers.plane.so/self-hosting/methods/docker-compose)
defaults to Commercial and has separate Community instructions. Do not install
Commercial by copying its first command. Inspect the chosen Community release's
Compose/environment files, preserve dependencies, and record source checksums.
Provisioning must not depend on an interactive download of an unpinned latest script.

## Media-server IaC

Paths in this section are relative to `jellyfin-stack`. New paths are proposed
implementation targets.

| Path | Change |
|---|---|
| `plane/compose.yml`, `plane/nginx.conf`, `plane/README.md` | Add pinned deployment, routing and operating commands; keep Plane's lifecycle separate from media applications. |
| `ansible/roles/media-server/tasks/plane.yml` | Add provisioning, scoped Compose startup, migration and health checks; include from the existing role. |
| `ansible/templates/plane.env.j2` | Render release-specific URLs and secrets with mode `0600` and `no_log`. |
| `ansible/group_vars/media_servers/vars.yml` | Declare domain, versions, networks, state paths and backup settings; use the existing ignored Vault file for secrets. |
| `docker-compose.yml` | Attach NPM to a dedicated Plane frontend network, with deployment scoped to avoid recreating unrelated services. |
| `ansible/roles/media-server/tasks/media.yml` | Extend existing Pi-hole record reconciliation without replacing unrelated entries. |
| `ansible/roles/media-server/tasks/plane-proxy.yml` | Provision certificate and proxy host idempotently using the authenticated NPM API after verifying its installed version. Do not modify NPM's database or generated files. |
| `homepage/services.yaml` | Add `Plane` under Apps, with `href: https://plane.morton.lan` and description `Ticket tracking`. A credential-bearing widget is unnecessary. |
| `.gitignore`, `ansible/README.md` | Ignore state, secrets and backup staging; document installation, renewal, upgrades and recovery. |

Retain the release's web, administration, collaboration, API, worker, scheduler
and migrator services. Give Plane its own database and storage. The
[architecture reference](https://developers.plane.so/self-hosting/plane-architecture)
describes PostgreSQL, Redis/Valkey, RabbitMQ and MinIO/S3 dependencies. Measure
available RAM, CPU and disk before deployment; live capacity was not inspected.
Use 8 GiB RAM as an initial planning allowance and budget disk for uploads plus
local backup staging, then measure with normal media workloads running.

Use a private backend network for stateful services and a frontend network
shared with NPM and Plane's routing container. Create the frontend network
idempotently before either Compose project starts, and declare it external with
the same explicit name in both projects. The routing container replaces the bundled
proxy using the [Community routing guide](https://developers.plane.so/self-hosting/govern/reverse-proxy):
web at `/`, administration at `/god-mode/`, sharing at `/spaces/`, collaboration
at `/live/`, API/auth/static routes, and the configured upload bucket path.
Preserve WebSocket upgrades, original host, forwarded HTTPS scheme and upload
limits across both proxies. Publish no database, cache, queue, MinIO console
or individual application ports. Confirm routes against the selected release.

Set `WEB_URL` and `CORS_ALLOWED_ORIGINS` to `https://plane.morton.lan`, plus any
additional external URL or CSRF settings that release requires. Test redirects,
login, live updates and attachment URLs through NPM. Configure SMTP and test
invitations and account recovery before cutover. Disable open registration and
public project sharing for the private Wish workspace.

Tracked Homepage LAN links currently use HTTP; no managed internal CA was found.
Inspect live NPM certificate state first. Reuse an appropriate internal CA if
available, otherwise establish one with its private key outside Git and the
VM. Issue and renew a certificate for `plane.morton.lan`, deploy it to NPM,
and install public CA trust in Donald's host/browser and the guest. Test the
MCP Python runtime's trust independently. Certificate verification must succeed
without bypass flags. Add certificate-expiry monitoring.

## Guest access and agent integration

| Wish path | Change |
|---|---|
| `ansible/roles/sandbox-network/defaults/main.yml` | Add service exceptions containing source, destination, protocol and port. |
| `ansible/roles/sandbox-network/templates/sandbox-nwfilter.xml.j2` | Permit `10.77.0.10` to reach `192.168.1.182` TCP 443 before the private-network drop. |
| `ansible/roles/sandbox-network/tasks/main.yml` | Validate exceptions and apply through the existing libvirt mechanism. |
| `ansible/inventory.yml.example` and private inventory | Configure the exception without putting media-server in the all-port `sandbox_net_pinholes` list. |
| `ansible/roles/sandbox-network/tasks/isolation-test-guest.yml` | Add positive Plane checks and negative checks for other server ports and the Windows guest. |
| `ansible/roles/agent-vm-guest/defaults/main.yml`, `tasks/main.yml`, `tasks/codex.yml`, `templates/` | Provision public CA trust, pinned integration dependencies, credential loading and both clients' configuration; preserve unrelated settings. |
| `ansible/README.md`, `docs/219-the-agent-sandbox.md` | Document the additional LAN exception, identity, DNS, trust and recovery. |

The filter is shared with `win11`, so the exception must include the Linux
VM's source address. The current filter does not enforce source anti-spoofing;
add and test IP/MAC bindings at each guest's libvirt interface before treating
the source address as guest identity. Include a Windows source-spoofing negative
test. A dedicated filter attached only to agent-vm is an alternative if binding
cannot be enforced. TCP 443 access permits **every HTTPS virtual host sharing
that IP and listener**. The proposed initial deployment accepts that reachability
while denying other ports. If isolation must distinguish Plane from other HTTPS
apps, reserve a dedicated ingress IP and adjust NPM's wildcard bindings before
rollout. An IP/port filter does not check HTTP Host or TLS SNI.

Keep guest DNS at libvirt's `10.77.0.1`. Verify that the host resolver serves the
Pi-hole record. If necessary, declare the mapping in
`ansible/roles/sandbox-network/templates/sandbox-network.xml.j2`; do not open
direct guest access to Pi-hole. Test from an actual sandboxed agent process,
including any client network restrictions, as well as from the guest shell.

Plane's [official MCP documentation](https://developers.plane.so/dev-tools/mcp-server)
supports local `plane-mcp-server stdio` with `PLANE_API_KEY`,
`PLANE_WORKSPACE_SLUG` and `PLANE_BASE_URL`. Set the URL explicitly to this
instance. Its hosted MCP cannot reach private instances; Community uses stdio
rather than the OAuth transport described for Commercial. Pin and install the
package during provisioning. The [vendor implementation](https://github.com/makeplane/plane-mcp-server)
is the preferred integration; the deployment CLI should not be assumed to be
a ticket-management CLI.

Register a proposed `wish-plane` stdio adapter in Claude Code's MCP configuration
and Codex's `[mcp_servers.wish-plane]` configuration. The
[Codex MCP reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
supports command, arguments and environment-variable forwarding. Use a secret-free
launcher with private credential files; do not put tokens in tracked JSON/TOML,
command arguments or logs. Use a dedicated Plane agent account, separate from
Donald's administrator account, with only required project permissions. Verify
actual API authorship before importing tickets.

The adapter filters text before either client receives it, restricts project,
workspace and operations, and checks human-thread restrictions on writes. Do not
register unrestricted vendor MCP alongside it: responses would bypass the shell
hooks. Stable account IDs determine trust; display names and labels do not.
Imported comments require original-author provenance. Trusting an importer must
never make all imported text trusted. Hooks remain tripwires, not a security
boundary, especially when credentials are readable in the guest.

Proposed tools are `tools/plane/planeread.py`, `tools/plane/planeagent.py` and
`tools/plane/mcp.py`, sharing one policy layer. Provide complete paginated listing,
filtered reads/citations, creation, comments, metadata changes and state readback.
Use the [REST API reference](https://developers.plane.so/api-reference/introduction)
for operations the pinned MCP cannot supply. Check API-version compatibility with
Community, respect rate-limit responses, and prevent duplicate writes after
ambiguous timeouts. Verify the full required operation set before declaring this
combination suitable; a cloud feature list is not acceptance evidence.

## Daily OneDrive backup

The existing media-server OneDrive container binds `/mnt/media/onedrive` as its
local sync directory. `ansible/roles/media-server/tasks/media.yml` configures an
allowlist containing only `/Pictures/*` and `/wish-backups/*`, and seeds its
refresh token without overwriting later token rotation. The existing Git backup
runs at 03:15 and uses `ansible/templates/wish-repository-backup.sh.j2`. It does
not cover Plane, and its local completion does not prove cloud upload.

Use direct restic-over-rclone upload for Plane. This requires new rclone
provisioning and OAuth setup, but gives the job a remote completion result and
encrypted incremental snapshots. Keep `Backups/Plane` outside the existing sync
client's allowlist and local sync directory, so two clients never manage the
same backup repository. Preserve existing Pictures and Git backup behavior.

| Item | Proposed implementation |
|---|---|
| IaC files | In jellyfin-stack, add `ansible/templates/plane-backup.sh.j2`, `plane-backup.service.j2`, `plane-backup.timer.j2`, and backup tasks in the Plane role. |
| Schedule | Run on media-server daily at 03:30 America/Chicago, using a persistent systemd timer, bounded runtime and a single-job lock. Check workload overlap before fixing the final time. |
| Destination | Set `RESTIC_REPOSITORY=rclone:plane-onedrive:Backups/Plane/media-server`; confirm the intended account, drive and folder at setup. |
| Credentials | Keep rclone OAuth configuration and the restic password restricted on media-server, with independent recovery copies in the password manager. The VM receives neither. |
| Content | Include a PostgreSQL dump and required roles, object data, rendered Plane secrets/configuration, deployment files, version/digest manifest and ticket provenance/mapping state. |
| Retention | Keep 14 daily, 8 weekly and 12 monthly successful snapshots, with stable host/tag/path grouping and restic retention. |
| Monitoring | Export last successful remote snapshot time, duration, size and errors to the media monitoring stack. Alert on failure or success older than 26 hours; prove notification delivery. |
| Recovery targets | Target no more than 24 hours of data loss when daily backups succeed, and restoration within four hours. Measure these; they are not current guarantees. |

Use [rclone's OneDrive backend](https://rclone.org/onedrive/) for authentication
and transport. Initial OAuth consent needs Donald's browser; unattended refresh
must work afterward. Preserve refreshed token state across Ansible reruns. Test
revocation and quota exhaustion handling, and verify the chosen account/drive.
No OneDrive access is required from `agent-vm`.

Use [restic's rclone backend](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)
for encrypted, deduplicated snapshots. Keep its password recoverable independently
of both server and repository. Restic owns the cloud repository; do not delete
its internal files using a generic age rule. Apply
[retention](https://restic.readthedocs.io/en/stable/060_forget.html) only after
successful backup and run periodic pruning under the same job lock.

The media-server job performs these steps:

1. Check staging capacity, credentials and repository access; acquire the lock.
   Use a private staging directory outside the checkout and OneDrive sync tree.
2. Put ingress into maintenance, stop scheduling new background work, drain
   active jobs, then stop all application writers, including API, collaboration
   and workers. Bound the wait; failure restores service and raises an alert.
3. With writers quiescent, create a logical PostgreSQL dump with matching database
   tools and copy object storage into the same staging set. Capture release-specific
   persistent queue/cache state if recovery requires it; document which transient
   state can be rebuilt. Do not copy a running database's data directory.
4. Record checksums and versions, complete the staging set, and restore service
   before uploading. Cleanup and systemd recovery handling must restore the
   pre-backup service state after failure. Test interruption during maintenance.
5. Back up the completed set with restic, check exit status and remote snapshot
   listing, and record its ID. Treat partial runs as failures. Retain failed-upload
   staging for bounded retry and alert before it fills disk. A new upload failure
   must not delete successful older snapshots.
6. Apply retention after success. Run regular repository integrity checks,
   rotating data-read checks and a complete restore drill before cutover and
   periodically afterward. Distinguish local capture from off-host success.

Restore from OneDrive into an isolated Compose project at the recorded database
and Plane versions, with notifications disabled and no production DNS. Restore
configuration, secrets, database and objects together. Verify login, counts,
comments, provenance and attachment downloads. The first drill must use remotely
retrieved data and independently recovered credentials, not staging files. Include
host-loss recovery for DNS, proxy certificate and client trust. Record downtime
and restoration duration. The [Plane backup reference](https://developers.plane.so/self-hosting/manage/backup-restore)
identifies database, uploads and configuration as recovery inputs; adapt the
procedure to the pinned Community release rather than using Commercial-only
Prime CLI commands.

## Wish rules, tools and documentation at cutover

Keep historical GitHub references intact. Future references use a linked Plane
identifier and title, generated by the filtered reader: `WISH-<number> (Title)`.
Use workspace slug `wish` and project identifier `WISH` as proposed defaults;
store API UUIDs separately from display identifiers.

| Paths in Wish | Required change |
|---|---|
| `AGENTS.md`, `.claude/rules/issues.md` | Declare Plane authoritative; replace list/read/write/citation commands and state checks. Preserve evidence-only ticket text, trust, human-thread restrictions, findings and closure gates. |
| `.claude/rules/documentation.md`, `.claude/rules/sessions.md` | Replace the work-list declaration and session resume commands. |
| `.claude/rules/commits.md` | Use Plane identifiers for new work; retain review, push and exact-SHA GitHub CI before manual closure. Disable integration-driven automatic closure. |
| `.claude/rules/feature-flags.md`, `.claude/rules/conversions.md`, `.claude/rules/delegating.md` | Review tracker-specific references while preserving acceptance requirements. Check `.agents/rules/` links instead of creating duplicate rules. |
| `.claude/skills/orchestrate/SKILL.md`, `.agents/skills/orchestrate/SKILL.md` | Switch queue discovery, priority ordering, filtered reads and blocked-work reconstruction together. |
| `~/.cache/wish/orchestrator-queue.md` on each orchestrator machine | Back up and translate identifiers in place at cutover; preserve decisions, deferrals, experiment details, handoff facts and Do not schedule entries. This is runtime state, not a new repository file. |
| `.claude/agents/{backlog-auditor,junior-dev,senior-analyst,changelog-writer}.md` and matching `.codex/agents/*.toml` | Update commands, tracker assumptions and citations in both definitions. |
| `tools/github/issueread.py`, `tools/github/ghtrust.py`, new `tools/plane/` | Keep legacy reads; implement Plane filtering for lists, descriptions, comments, search, JSON and citations. |
| `tools/wishagent.py` | Retire only active ticket writes after migration. Retain `push-token` and `git-credential` for GitHub repository access. |
| `.claude/hooks/check-issue-reads.py`, `.claude/hooks/check-issue-writes.py`, `.claude/hooks/issue-titles-context.py` | Update guards and startup context; cover adapter use and accidental writes to the old tracker. |
| `.claude/settings.json`, `.codex/hooks.json`, `.agents/skills/orchestrate/scripts/check_hooks.py` | Wire and verify both clients' hooks, including Codex trust after configuration changes. |
| `.claude/hooks/check-issue-titles.py`, `.claude/hooks/check-gh-issue-titles.py` | Update parsing if retained. These are not currently wired in Claude settings and cannot count as active enforcement. |
| `.github/ISSUE_TEMPLATE/{bug,enhancement,question}.md`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/workflows/issue-origin.yml` | Preserve public intake/origin handling. Reuse template structures in the Plane wrapper; verify native template availability before depending on it. |
| `docs/218-the-wish-agent-bot.md`, `docs/219-the-agent-sandbox.md` | Document separate GitHub/Plane credentials, filtering, trust, setup, rotation and recovery. |
| `docs/160-why-these-rules.md`, `docs/235-destination-game-acceptance-runs.md`, `docs/227-editor-open-save-as.md` | Record migration reasoning and update operational closure/priority guidance without rewriting historical evidence. |
| `tests/github/test_{ghtrust,issueread,wishagent}.py`, `tests/hooks/test_{check_issue_reads,check_issue_writes,issue_titles_context}.py`, new `tests/plane/` | Test policy, pagination, attribution, failures, imports and adapters; retain GitHub credential tests. |
| `tests/suite/test_repository_contents.py`, directory README tables and `INDEX.md` | Update citation checks and inventories. Review `tests/suite/test_toolpaths.py` if paths move. Leave the top-level README for Donald's separate authorization. |

Map High/Medium/Low to corresponding native Plane priorities and require exactly
one; avoid a competing priority label. Preserve `bug`, `enhancement`, `question`,
origin labels and Donald-specific `blocked` semantics. Map workflow states using
the chosen release's backlog/unstarted/started/completed/cancelled groups;
distinguish fixed work from duplicate or invalid reports. Keep comments explaining
metadata changes and factual corrections. Labels cannot grant permission or
replace original authorship.

## Implementation and migration order

| Stage | Exit evidence |
|---|---|
| 1. Preflight | Record host capacity, versions, live NPM/TLS state, DNS, SMTP and OneDrive account/folder. Prove required Community API/MCP operations in a disposable project. |
| 2. Infrastructure | Ansible rerun is idempotent; services/migrations succeed; Homepage opens Plane; trusted HTTPS login, WebSockets and attachments work. |
| 3. Isolation and clients | Both clients reach Plane from agent-vm. Media SSH, NPM81, Homepage3000 and unrelated LAN targets stay denied. Win11 gains no exception. Use reachable host-side controls so a stopped service cannot masquerade as isolation. |
| 4. Backup | The scheduled media-server job creates a verified OneDrive snapshot; failure alerts work; independent restore meets measured recovery targets. |
| 5. Migration rehearsal | Export source metadata/history privately, map GitHub IDs to Plane UUIDs/URLs and import a representative subset. Preserve source authors, timestamps, trust, attachments, dependencies and acceptance evidence. |
| 6. Policy acceptance | Both clients pass trusted/withheld reads, complete pagination, citations, agent-authored creation/comments, human-thread write blocking, priority explanations, correction comments, retries and closure readback. GitHub push/CI still work. |
| 7. Cutover | Pause ticket writers, export/reconcile the final delta, compare open/closed counts and comment/attachment histories, then activate rules/tools in both clients together. Resume with Plane authoritative. |

Migrate open work first and preserve a read-only source archive of closed history;
import closed tickets referenced by active work as needed. Record omitted fields
or failed attachments. An idempotent migration ledger must preserve original trust
independently of mutable ticket text and belong to backed-up service state.
Ordinary agent reads stay filtered; a migration tool can transfer opaque source
text without printing it into an agent's context.

Keep public GitHub reporting because outside players cannot open a LAN URL.
Donald can authorize internal tickets linked to public reports; retain the rule
against agent comments in human threads. Public release notes must describe
changes without depending on inaccessible Plane links. Existing GitHub links
remain valid. Moving a ticket does not complete its work; do not bulk-close
originals as fixed merely because they were imported.

Before cutover, rollback discards the rehearsal project and continues the unchanged
GitHub queue. After cutover, pause writers and reconcile Plane-only changes before
switching back; never operate two writable authoritative queues. For a failed
upgrade, restore matching pre-upgrade database, objects and configuration with the
previous images. An image downgrade does not reverse a database migration.

Media deployment and VM networking belong to the host maintenance role. Wish
policy/tool implementation belongs to the Wish implementation role when assigned.
Account bootstrap, OAuth consent and production migration remain explicit stages;
record actual versions, counts, timestamps, snapshot IDs and failures at each gate.
