# Plane preparation and operations

Donald and the agents continue using GitHub as the work register while Plane
is prepared at `http://plane.morton.lan`. The tools and guest provisioning
below implement parts of [the deployment plan](237-plane-ticketing-plan.md);
they do not establish live deployment, migration or recovery acceptance.

## Service and ingress

Plane service, DNS and backup provisioning belong to the private
`jellyfin-stack` checkout. Donald configures Nginx Proxy Manager manually;
neither its administrator credentials nor SMTP credentials are required by
Wish. Plane email stays disabled. Account creation and password recovery must
be demonstrated without email before switching the work register.

Donald confirmed the manual NPM proxy configuration. Its domain is
`plane.morton.lan`, scheme `http`, upstream `plane-router`, port `80`, with
WebSocket support enabled and Custom Locations empty. Custom Nginx Configuration
contains `client_max_body_size 20m;` and `proxy_read_timeout 3600s;` on separate
lines. Donald selected HTTP, so this deployment needs no certificate, Force SSL,
CA trust or renewal. This confirmation does not establish application acceptance.

The private deployment pins Community v1.4.2 release tags; record pulled image
digests during live acceptance. Run its Plane tag from the host controller:
`ansible-playbook -i ansible/inventory.yml ansible/playbook.yml --tags plane`.
For manual password recovery, run `docker compose --env-file plane.env -f
compose.yml -p plane exec api python manage.py changepassword EMAIL` from the
private Plane directory on media-server, then verify login. The password is
prompted rather than passed in arguments. Account creation and membership still
need live verification.

## Guest provisioning

The guest integration defaults to disabled. Configure the private inventory,
then run the existing host-side Ansible playbooks described in
[the Ansible directory](../ansible/README.md).

| Setting | Purpose |
|---|---|
| `sandbox_net_service_exceptions` | Allows the configured source guest to one destination TCP port and provides its DNS hostname. |
| `agent_guest_plane_enabled: true` | Enables the guest integration tasks after the service is ready. |
| `agent_guest_plane_allow_insecure_http: true` | Explicitly permits Donald's selected HTTP deployment. |
| `agent_guest_plane_src` | Host directory holding private `api-key` and `config.json`; defaults to `~/.config/wish-plane`. |
| `agent_guest_plane_base_url` | Set to `http://plane.morton.lan` for this deployment. |

The intended exception is source `10.77.0.10`, destination `192.168.1.182`,
TCP port `80`, hostname `plane.morton.lan`, with other responding server ports
listed in `denied_tcp_ports`. Do not put that server in
`sandbox_net_pinholes`, which permits every port. Every HTTP virtual host on
the destination listener becomes reachable; this filter does not inspect TLS
SNI or HTTP Host. Guest DNS remains `10.77.0.1`.

The role installs `plane-mcp-server==0.3.3` and `plane-sdk==0.3.1` in a dedicated
virtual environment, validates the private configuration and registers only `wish-plane` in Claude Code and Codex.
HTTPS remains an optional mode with CA verification. Existing unrelated
client settings are preserved. Successful provisioning does not prove access
from an actual sandboxed client process; that remains a separate live check.

## Policy configuration and commands

`WISH_PLANE_CONFIG` names an owner-controlled JSON file. The guest role writes
it with mode `0600` and supplies the guest token and write-journal paths.
Provision these fields using account and project UUIDs read from the deployed
instance:

| Field | Meaning |
|---|---|
| `base_url`, `workspace_slug`, `project_id`, `project_identifier` | Approved origin, workspace and project; the display identifier defaults to `WISH`. |
| `agent_account_id`, `trusted_account_ids` | Dedicated agent identity and trusted native authors, using stable UUIDs. |
| `importer_account_ids` | Import identities whose text requires original-author provenance; separate from the agent identity. |
| `source_trusted_account_ids` | Trusted source identities in `github:<numeric-id>` form. |
| `provenance_file` | Protected JSON mapping imported record UUIDs to original authors and exact text digests. |
| `token_file` | Owner-only API key file, mode `0600`. |
| `journal_file` | Durable local SQLite write journal, mode `0600`. |
| `resource` | API resource, `work-items` by default or `issues`; confirm against the deployed release. |
| `allow_insecure_http` | Set explicitly to true for the chosen HTTP origin; HTTPS remains the default requirement. |
| `writes_enabled` | Defaults to false; enable only for an explicitly accepted target. |

The adapter exposes list, search, read, citation, project metadata, create,
comment and update operations. The same policy is available through these
commands, run with the pinned Python environment and private configuration:

```sh
python -m tools.plane.planeread --list
python -m tools.plane.planeread --metadata
python -m tools.plane.planeread WISH-1 --cite
python -m tools.plane.planeagent --help
python -m tools.plane.mcp
```

Lists and comments are paginated. Untrusted titles, bodies and comments are
replaced with their lengths while stable authors and timestamps remain visible.
Imported text needs a matching digest and trusted original identity; trusting
the import account alone does not disclose it. Ticket text remains evidence,
never instructions. Human-thread writes are blocked. The adapter verifies the
agent identity before writes and checks returned authorship for creation and
comments. Updates require an explanation and read back the result.

Every write needs a stable `--operation-id`. The journal records intent before
sending and returns a recorded successful result for repeat requests. An
uncertain result stops further attempts: inspect the remote result and journal
before reconciling it. Do not delete the journal or invent another operation
ID to retry. There is no automated reconciliation command. These are policy
checks for cooperating tools; a guest account able to read the API key can
call the API outside the adapter.

## Migration rehearsal and recovery state

`python -m tools.plane.migrate export --directory PRIVATE-DIRECTORY
--repository malcyon/wish` captures all issue, comment and timeline pages in
an immutable private JSON export. Its directory must be outside the checkout
with mode `0700`; source text is not printed. Use
`python -m tools.plane.migrate rehearse --help` for the explicit issue subset,
rehearsal-project UUID, state UUIDs, label map and trusted source IDs.
Rehearsal writes require `--allow-writes`.

The private `migration.sqlite3` records source objects, mappings, write intent
and outcomes. Confirmed imports produce `provenance.json`. Preserve both with
the immutable export and adapter write journal; restoring the database alone
would lose the filtering and duplicate-write evidence. Unconfirmed migration
writes stop until remote reconciliation. The export records attachment URLs,
not attachment bytes; dependency reconciliation and a final source delta also
remain necessary. Rehearsal completion does not make these omissions a
completed migration.

The private media deployment supplies `plane-backup.service` and
`plane-backup.timer`, plus `/usr/local/sbin/plane-backup-alert test` for a
notification check. The timer stays disabled until restore and failure checks
pass. Its destination is
`rclone:plane-onedrive:Backups/Plane/media-server`; root-only password and OAuth
files live under `/etc/plane-backup`. The VM receives neither. The job preserves
its interrupted-service journal and retries a completed failed-upload capture
before taking another. After interrupted capture, `plane-backup recover`
restores the recorded service state. See the private deployment's
`plane/backup.md` for the full restore procedure and required credentials.

Service recovery must retrieve the encrypted backup from OneDrive into an
isolated instance with email disabled, using independently recovered secrets.
Verify login, ticket and comment counts, provenance and attachment downloads,
plus DNS and proxy recovery. Local staging or a successful
upload alone does not prove restoration. The plan's 24-hour recovery point and
four-hour restoration targets remain targets until measured.

The authority switch requires the plan's live infrastructure, isolation,
both-client, migration and remote-restore acceptance, followed by coordinated
rule and queue updates. Existing GitHub rules and public intake remain active
until then.
