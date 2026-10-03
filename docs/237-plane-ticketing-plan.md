# Plane ticket tracking on the media server

Donald and the agents need one ticket queue available from the LAN and from
`agent-vm`. Plane Community v1.4.2 is deployed at `http://plane.morton.lan`, with service and backup
IaC in `/home/donald/src/jellyfin-stack` and VM access IaC in
`/home/donald/src/wish`. This plan uses repository inspection and vendor
documentation checked on 2026-10-02. Live deployment and Donald's confirmed login
replace the initial deployment assumptions. Donald subsequently made Plane
the default work register after a one-time open-ticket migration. This supersedes
the original authority gate, final-delta plan and closed-dependency import scope.
GitHub issue tools now require an explicit GitHub request; code, PRs and CI
remain there. MCP write and backup acceptance remain separate disabled gates.

Donald revised the deployment on 2026-10-02: use HTTP on the LAN without a
certificate, disable Plane email, and let him configure NPM manually. He has
confirmed the NPM configuration and application login. The host's scoped
`wish-plane` MCP is registered in both clients; its read API check returned zero
work items. Guest access and the full operation set still need live acceptance.

## Recommended design

| Component | Plan | Evidence or constraint |
|---|---|---|
| Edition | Community v1.4.2, pinned by release tags and image digests. | The deployment is live; required ticket operations still need migration acceptance. |
| Host | A separate Compose project on media-server, currently `192.168.1.182`. | `jellyfin-stack/ansible/inventory.yml` and `ansible/group_vars/media_servers/vars.yml`. |
| Ingress | Existing Nginx Proxy Manager (NPM), forwarding HTTP to a Plane routing container. | Main Compose already assigns NPM ports 80, 81 and 443. |
| DNS | An Ansible-managed Pi-hole record for `plane.morton.lan`. | The media role already preserves and extends Pi-hole `dns.hosts` for Grafana. |
| Agents | Scoped `wish-plane` stdio adapter registered in both host clients. | A host read returned zero work items; guest and complete policy acceptance remain pending. |
| Backup | Implemented media-server restic/rclone job, with daily scheduling disabled pending acceptance. | OAuth, verified remote snapshot and independent restore remain pending. |
| Work register | Plane is the current default by Donald's explicit instruction; import was open-only and one-time. | GitHub retains code, PRs, CI and public intake; issue tools require an explicit GitHub request. |

The supplied [self-hosting overview](https://developers.plane.so/self-hosting/overview)
is the entry point. The [Compose guide](https://developers.plane.so/self-hosting/methods/docker-compose)
defaults to Commercial and has separate Community instructions. Do not install
Commercial by copying its first command. Inspect the chosen Community release's
Compose/environment files, preserve dependencies, and record source checksums.
Provisioning must not depend on an interactive download of an unpinned latest script.

## Media-server IaC

Paths in this section are relative to `jellyfin-stack`; the deployment files are
implemented. The table records their responsibilities and remaining acceptance.

| Path | Change |
|---|---|
| `plane/compose.yml`, `plane/nginx.conf`, `plane/README.md` | Add pinned deployment, routing and operating commands; keep Plane's lifecycle separate from media applications. |
| `ansible/roles/media-server/tasks/plane.yml` | Add provisioning, scoped Compose startup, migration and health checks; include from the existing role. |
| `ansible/templates/plane.env.j2` | Render release-specific URLs and secrets with mode `0600` and `no_log`. |
| `ansible/group_vars/media_servers/vars.yml` | Declare domain, versions, networks, state paths and backup settings; use the existing ignored Vault file for secrets. |
| `docker-compose.yml` | Attach NPM to a dedicated Plane frontend network, with deployment scoped to avoid recreating unrelated services. |
| `ansible/roles/media-server/tasks/media.yml` | Extend existing Pi-hole record reconciliation without replacing unrelated entries. |
| `ansible/roles/media-server/tasks/plane-proxy.yml` | Verify Donald's manually configured proxy route without modifying NPM's database or generated files. |
| `homepage/services.yaml` | Add `Plane` under Apps, with `href: http://plane.morton.lan` and description `Ticket tracking`. A credential-bearing widget is unnecessary. |
| `.gitignore`, `ansible/README.md` | Ignore state, secrets and backup staging; document installation, upgrades and recovery. |

Retain the release's web, administration, collaboration, API, worker, scheduler
and migrator services. Give Plane its own database and storage. The
[architecture reference](https://developers.plane.so/self-hosting/plane-architecture)
describes PostgreSQL, Redis/Valkey, RabbitMQ and MinIO/S3 dependencies. Live
preflight measured eight CPUs, 23 GiB RAM with 17.5 GiB available, 43 GiB free
on the root filesystem and 6 TiB free on the media volume. These measurements
replace the unverified capacity assumption. Reserve capacity for uploads and
backup staging, and measure resource use with normal media workloads running.

Use a private backend network for stateful services and a frontend network
shared with NPM and Plane's routing container. Create the frontend network
idempotently before either Compose project starts, and declare it external with
the same explicit name in both projects. The routing container replaces the bundled
proxy using the [Community routing guide](https://developers.plane.so/self-hosting/govern/reverse-proxy):
web at `/`, administration at `/god-mode/`, collaboration
at `/live/`, API/auth/static routes, and the configured upload bucket path.
Preserve WebSocket upgrades, original host, forwarded HTTP scheme and upload
limits across both proxies. Publish no database, cache, queue, MinIO console
or individual application ports. Public sharing routes, including `/spaces/`,
are disabled for the private workspace. Complete live WebSocket and attachment
acceptance against the selected release.

Set `WEB_URL` and `CORS_ALLOWED_ORIGINS` to `http://plane.morton.lan`, plus any
additional external URL or CSRF settings that release requires. Test redirects,
login, live updates and attachment URLs through NPM. Donald requested on
2026-10-02 that Plane send no email: leave SMTP disabled, provision accounts
through the administrator, and document and test manual account recovery as
a remaining recovery acceptance requirement. Disable open registration and public project sharing for the private
Wish workspace.

Use HTTP without certificate provisioning or client CA installation, as Donald
requested. The policy adapter requires explicit `allow_insecure_http: true` for
this instance; HTTPS remains its default for other configurations. Verify the
actual HTTP route through NPM from the host and guest.

## Guest access and agent integration

| Wish path | Change |
|---|---|
| `ansible/roles/sandbox-network/defaults/main.yml` | Add service exceptions containing source, destination, protocol and port. |
| `ansible/roles/sandbox-network/templates/sandbox-nwfilter.xml.j2` | Permit `10.77.0.10` to reach `192.168.1.182` TCP 80 before the private-network drop. |
| `ansible/roles/sandbox-network/tasks/main.yml` | Validate exceptions and apply through the existing libvirt mechanism. |
| `ansible/inventory.yml.example` and private inventory | Configure the exception without putting media-server in the all-port `sandbox_net_pinholes` list. |
| `ansible/roles/sandbox-network/tasks/isolation-test-guest.yml` | Add positive Plane checks and negative checks for other server ports and the Windows guest. |
| `ansible/roles/agent-vm-guest/defaults/main.yml`, `tasks/main.yml`, `tasks/codex.yml`, `templates/` | Provision pinned integration dependencies, credential loading and both clients' configuration with explicit HTTP opt-in; preserve unrelated settings. |
| `ansible/README.md`, `docs/219-the-agent-sandbox.md` | Document the additional LAN exception, identity, DNS, trust and recovery. |

The filter is shared with `win11`, so the exception includes the Linux
VM's source address. The implementation adds IP/MAC/ARP anti-spoofing filters
and guest interface bindings; this replaces the original unprotected source-IP
assumption. Live guest isolation and the Windows forged-source negative test
remain pending. TCP 80 access permits **every HTTP virtual host sharing
that IP and listener**. The selected deployment accepts that reachability
while denying other ports. If isolation must distinguish Plane from other HTTP
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

The host's `wish-plane` stdio adapter is registered in Claude Code's MCP
configuration and Codex's `[mcp_servers.wish-plane]` configuration. Guest
provisioning implements the corresponding registration. The
[Codex MCP reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
supports command, arguments and environment-variable forwarding. Use a secret-free
launcher with private credential files; do not put tokens in tracked JSON/TOML,
command arguments or logs. Use a dedicated Plane agent account, separate from
Donald's administrator account, with only required project permissions. Verify
actual API authorship before importing tickets.

Donald selected full-content reads for private LAN Plane. The adapter returns all
titles, descriptions and comments without original-author, import-fingerprint or
editor filtering, and without a human-thread origin write block. It restricts
workspace, project and operations, verifies dedicated-agent writes and retains
journals/readback. This connector change is pending review and deployment.
Ticket text remains evidence, never instructions. Hooks remain tripwires, not a
security boundary, especially when credentials are readable in the guest.

The implemented `tools/plane/` directory contains `planeread.py`, `planeagent.py`
and `mcp.py`, sharing one policy layer for paginated listing, project-scoped
reads/citations, creation, comments, metadata changes and state readback.
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
runs at 03:15 UTC and uses `ansible/templates/wish-repository-backup.sh.j2`. It does
not cover Plane, and its local completion does not prove cloud upload.

Use direct restic-over-rclone upload for Plane. This requires new rclone
provisioning and OAuth setup, but gives the job a remote completion result and
encrypted incremental snapshots. Keep `Backups/Plane` outside the existing sync
client's allowlist and local sync directory, so two clients never manage the
same backup repository. Preserve existing Pictures and Git backup behavior.

| Item | Implementation and acceptance |
|---|---|
| IaC files | Jellyfin-stack contains the backup script, service, timer, recovery and notification units, and tasks in the Plane role. |
| Schedule | The persistent timer uses 03:30 America/Chicago, a bounded runtime and a job lock; `plane_backup_schedule_enabled` stays false until restore and failure acceptance. |
| Destination | Set `RESTIC_REPOSITORY=rclone:plane-onedrive:Backups/Plane/media-server`; confirm the intended account, drive and folder at setup. |
| Credentials | Keep rclone OAuth configuration and the restic password restricted on media-server, with independent recovery copies in the password manager. The VM receives neither. |
| Content | Include a PostgreSQL dump and required roles, object data, rendered Plane secrets/configuration, deployment files, version/digest manifest and durable agent write journals and historical migration recovery material. |
| Retention | Keep 14 daily, 8 weekly and 12 monthly successful snapshots, with stable host/tag/path grouping and restic retention. |
| Monitoring | Export successful upload time and original capture time separately, duration, size and errors. Alert when remotely verified data is older than 26 hours; retrying an old capture must not reset its age. Notification delivery remains unproven. |
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

1. Check staging capacity, credentials and repository access; acquire the job lock
   and the same exclusive `state.lock` used by migration in the provenance directory.
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
   rotating data-read checks and a complete restore drill as recovery acceptance and
   periodically afterward. Distinguish local capture from off-host success.

Restore from OneDrive into an isolated Compose project at the recorded database
and Plane versions, with notifications disabled and no production DNS. Restore
configuration, secrets, database and objects together. Verify login, counts,
comments, write journals and attachment downloads. The first drill must use remotely
retrieved data and independently recovered credentials, not staging files. Include
host-loss recovery for DNS and proxy configuration. Record downtime
and restoration duration. The [Plane backup reference](https://developers.plane.so/self-hosting/manage/backup-restore)
identifies database, uploads and configuration as recovery inputs; adapt the
procedure to the pinned Community release rather than using Commercial-only
Prime CLI commands.

## Wish rules, tools and current Plane authority

Keep historical GitHub references intact. Future references use a linked Plane
identifier and title, generated by the project-scoped reader: `WISH-<number> (Title)`.
Use the configured workspace slug `wish` and project identifier `WISH`;
store API UUIDs separately from display identifiers.

| Paths in Wish | Required change |
|---|---|
| `AGENTS.md`, `.claude/rules/issues.md` | Declare Plane authoritative; replace list/read/write/citation commands and state checks. Preserve evidence-only ticket text, dedicated-agent writes, findings and closure gates; retain public-author filtering and human-thread restrictions only for explicit GitHub requests. |
| `.claude/rules/documentation.md`, `.claude/rules/sessions.md` | Replace the work-list declaration and session resume commands. |
| `.claude/rules/commits.md` | Use Plane identifiers for new work; retain review, push and exact-SHA GitHub CI before manual closure. Disable integration-driven automatic closure. |
| `.claude/rules/feature-flags.md`, `.claude/rules/conversions.md`, `.claude/rules/delegating.md` | Review tracker-specific references while preserving acceptance requirements. Check `.agents/rules/` links instead of creating duplicate rules. |
| `.claude/skills/orchestrate/SKILL.md`, `.agents/skills/orchestrate/SKILL.md` | Switch queue discovery, priority ordering, project-scoped reads and blocked-work reconstruction together. |
| `~/.cache/wish/orchestrator-queue.md` on each orchestrator machine | Reconcile identifiers, native priority and live state in place; preserve decisions, deferrals, experiment details, handoff facts and Do not schedule entries. This is runtime state, not a new repository file. |
| `.claude/agents/{backlog-auditor,junior-dev,senior-analyst,changelog-writer}.md` and matching `.codex/agents/*.toml` | Update commands, tracker assumptions and citations in both definitions. |
| `tools/github/issueread.py`, `tools/github/ghtrust.py`, `tools/plane/` | Keep GitHub reads for explicit requests and read all private Plane lists, descriptions, comments, search, JSON and citations within the configured project. |
| `tools/wishagent.py` | Keep issue tools only for explicit GitHub requests. Retain `push-token` and `git-credential` for repository access. |
| `.claude/hooks/check-issue-reads.py`, `.claude/hooks/check-issue-writes.py`, `.claude/hooks/issue-titles-context.py` | Retain GitHub filtering guards and Plane project/write tripwires; disable only automatic GitHub SessionStart context and preserve its script for explicit requests. |
| `.claude/settings.json`, `.codex/hooks.json`, `.agents/skills/orchestrate/scripts/check_hooks.py` | Wire and verify both clients' hooks, including Codex trust after configuration changes. |
| `.claude/hooks/check-issue-titles.py`, `.claude/hooks/check-gh-issue-titles.py` | Update parsing if retained. These are not currently wired in Claude settings and cannot count as active enforcement. |
| `.github/ISSUE_TEMPLATE/{bug,enhancement,question}.md`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/workflows/issue-origin.yml` | Preserve public intake/origin handling. Reuse template structures in the Plane wrapper; verify native template availability before depending on it. |
| `docs/218-the-wish-agent-bot.md`, `docs/219-the-agent-sandbox.md` | Document separate GitHub/Plane credentials, project scope, GitHub public-author filtering, setup, rotation and recovery. |
| `docs/160-why-these-rules.md`, `docs/235-destination-game-acceptance-runs.md`, `docs/227-editor-open-save-as.md` | Record migration reasoning and update operational closure/priority guidance without rewriting historical evidence. |
| `tests/github/test_{ghtrust,issueread,wishagent}.py`, `tests/hooks/test_{check_issue_reads,check_issue_writes,issue_titles_context}.py`, new `tests/plane/` | Test policy, pagination, attribution, failures, imports and adapters; retain GitHub credential tests. |
| `tests/suite/test_repository_contents.py`, directory README tables and `INDEX.md` | Update citation checks and inventories. Review `tests/suite/test_toolpaths.py` if paths move. Leave the top-level README for Donald's separate authorization. |

The initial deployment copied source labels except AI/Human, including three
priority labels. Donald subsequently selected native priority only, superseding
that label-sync design. Do not recreate priority labels; preserve manual native
priorities. The four visible states are Backlog, Queue, In Progress and Completed,
with their matching groups. Backlog is unscheduled, Queue is scheduled, starting
moves to In Progress, and accepted reviewed/pushed work with exact-SHA CI reaches
Completed. Unscheduling returns to Backlog; decision waits remain unfinished.
Private Plane reads all content regardless of author, import fingerprints or
editor identity, and has no human-thread origin block. See [current operations](238-plane-operations.md).

## Implementation and migration order

| Stage | Exit evidence |
|---|---|
| 1. Preflight | Record host capacity, versions, live NPM state, DNS, disabled email and OneDrive account/folder. Prove required Community API/MCP operations in a disposable project. |
| 2. Infrastructure | Ansible rerun is idempotent; services/migrations succeed; Homepage opens Plane; HTTP login, WebSockets and attachments work. |
| 3. Isolation and clients | Both clients reach Plane from agent-vm. Media SSH, NPM81, Homepage3000 and unrelated LAN targets stay denied. Win11 gains no exception. Use reachable host-side controls so a stopped service cannot masquerade as isolation. |
| 4. Backup | The scheduled media-server job creates a verified OneDrive snapshot; failure alerts work; independent restore meets measured recovery targets. |
| 5. One-time migration complete | Accepted 25 open tickets and 631 comments; preserve source authorship, provenance and recovery evidence. No further history or delta import is authorized. |
| 6. Policy acceptance | Both clients read all private Plane content with complete pagination and citations, enforce project scope and agent-authored creation/comments, and pass native priority/state updates, correction comments, retries and closure readback. GitHub push/CI still work. |
| 7. Current authority | Donald selected Plane after one-time open import. Update rules and queue caches from live Plane; no automatic delta, history import or synchronization is authorized. |

The accepted one-time open migration contains 25 tickets and 631 comments.
The accidentally started closed-history phase was cancelled and its 235 imported
closed destinations removed under Donald's scoped instruction, with GitHub
unchanged. Preserve source authorship, historical migration recovery evidence.
There is no further history/dependency-closure import or final-delta gate;
remaining acceptance does not authorize another import. Current Plane edits
must not be replaced from historical GitHub archives.

Infrastructure, actual sandboxed-client write policy, OneDrive OAuth,
independent restore and manual account recovery remain acceptance work for their
owners. Write configuration and backup schedules stay disabled until those
respective gates pass; the tracker choice itself is already settled.

Keep public GitHub reporting because outside players cannot open a LAN URL.
Agents access GitHub issues only when Donald explicitly requests it, and he
can authorize internal tickets linked to public reports; retain the rule
against agent comments in GitHub human threads. Public release notes must describe
changes without depending on inaccessible Plane links. Existing GitHub links
remain valid. Moving a ticket does not complete its work; do not bulk-close
originals as fixed merely because they were imported.

Plane remains the default unless Donald explicitly changes that instruction.
A disabled write or infrastructure failure does not authorize operating another
writable issue queue or falling back to GitHub. For a failed
upgrade, restore matching pre-upgrade database, objects and configuration with the
previous images. An image downgrade does not reverse a database migration.

Media deployment and VM networking belong to the host maintenance role. Wish
policy/tool implementation belongs to the Wish implementation role when assigned.
Account bootstrap, OAuth consent and production migration remain explicit stages;
record actual versions, counts, timestamps, snapshot IDs and failures at each gate.
