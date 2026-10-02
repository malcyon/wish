#!/usr/bin/env python3
"""Export GitHub history privately and rehearse imports with durable provenance."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class MigrationError(Exception):
    """Report a migration failure without exposing source text or credentials."""


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def private_directory(path: Path) -> Path:
    """Require an owner-only directory outside the checkout for source history."""
    path = path.absolute()
    repository = Path(__file__).resolve().parents[2]
    if path.is_symlink() or path.resolve().is_relative_to(repository):
        raise MigrationError("Private migration state must be outside the checkout")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise MigrationError("Migration directory must be owned by this user with mode 0700")
    return path


def github_pages(endpoint: str) -> list[dict]:
    """Capture all API pages without exposing GitHub text on either output stream."""
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", "--paginate", "--slurp", endpoint],
            capture_output=True, text=True, timeout=300, check=True,
        )
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError
        return [item for page in pages for item in page]
    except (subprocess.SubprocessError, OSError, ValueError) as from_error:
        raise MigrationError("GitHub export failed; source output withheld") from from_error


def export_source(directory: Path, repository: str, fetch: Callable = github_pages) -> Path:
    """Keep opaque issues, comments and timeline events in an immutable private export."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise MigrationError("Repository must be an owner/name pair")
    directory = private_directory(directory)
    issues = fetch(f"repos/{repository}/issues?state=all&per_page=100")
    records = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        number = issue.get("number")
        if type(number) is not int or number < 1:
            raise MigrationError("Source issue has no valid number")
        prefix = f"repos/{repository}/issues/{number}"
        records.append({"issue": issue,
                        "comments": fetch(f"{prefix}/comments?per_page=100"),
                        "timeline": fetch(f"{prefix}/timeline?per_page=100")})
    snapshot = {"version": 1, "repository": repository,
                "exported_at": datetime.now(UTC).isoformat(), "records": records,
                "limitations": ["Attachment bytes have not been downloaded",
                                "Timeline relations require dependency reconciliation",
                                "Concurrent source writes require a final delta export"]}
    output = directory / f"github-{digest(snapshot)}.json"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(snapshot, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return output


class Ledger:
    """Keep source authorship and write intent independently of editable Plane text."""

    def __init__(self, directory: Path, project_id: str):
        directory = private_directory(directory)
        path = directory / "migration.sqlite3"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        os.close(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise MigrationError("Migration ledger must have mode 0600")
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS scope (project TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS objects (
                source_key TEXT PRIMARY KEY, kind TEXT NOT NULL,
                source TEXT NOT NULL, source_digest TEXT NOT NULL,
                author_id TEXT, trusted INTEGER NOT NULL,
                payload TEXT NOT NULL, payload_digest TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned', plane_id TEXT UNIQUE,
                parent_key TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS revisions (
                revision INTEGER PRIMARY KEY, source_key TEXT NOT NULL,
                source TEXT NOT NULL, payload TEXT NOT NULL,
                source_digest TEXT NOT NULL, author_id TEXT, trusted INTEGER NOT NULL,
                captured_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS origins (
                source_key TEXT PRIMARY KEY, human_thread INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS destinations (
                plane_id TEXT PRIMARY KEY, record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                source_key TEXT NOT NULL, kind TEXT NOT NULL,
                detail TEXT NOT NULL, status TEXT NOT NULL,
                UNIQUE(source_key, kind, detail)
            );
        """)
        self.db.execute("BEGIN IMMEDIATE")
        scopes = self.db.execute("SELECT project FROM scope").fetchall()
        if scopes and scopes != [(project_id,)]:
            self.db.close()
            raise MigrationError("Ledger belongs to a different rehearsal project")
        self.db.execute("INSERT OR IGNORE INTO scope VALUES (?)", (project_id,))
        self.db.commit()
        self.project_id = project_id

    def close(self):
        self.db.close()

    def record(self, key: str, kind: str, source: dict, payload: dict,
               trusted_ids: frozenset[str], parent: str | None = None, reconcile: bool = False):
        author = source.get("user") or {}
        author_id = str(author["id"]) if type(author.get("id")) is int else None
        trusted = author_id is not None and author_id in trusted_ids
        previous = self.db.execute(
            "SELECT source_digest, payload_digest, trusted FROM objects WHERE source_key=?", (key,)
        ).fetchone()
        expected = (digest(source), digest(payload), int(trusted))
        if previous and previous != expected:
            row = self.db.execute(
                "SELECT source,payload,source_digest,author_id,trusted,status,plane_id FROM objects WHERE source_key=?", (key,)
            ).fetchone()
            if not reconcile or row[5] not in {"complete", "planned"}:
                raise MigrationError("Source, trust or mapping changed; reconcile before continuing")
            if row[3] != author_id or row[4] != int(trusted):
                raise MigrationError("Original author or trust changed; automatic reconciliation blocked")
            self.db.execute("INSERT INTO revisions (source_key,source,payload,source_digest,author_id,trusted,captured_at) VALUES (?,?,?,?,?,?,?)",
                            (key, *row[:5], datetime.now(UTC).isoformat()))
            status = "planned_update" if row[6] and previous[1] != expected[1] else row[5]
            self.db.execute("UPDATE objects SET source=?,source_digest=?,payload=?,payload_digest=?,status=?,updated_at=? WHERE source_key=?",
                            (json.dumps(source), expected[0], json.dumps(payload), expected[1], status, source.get("updated_at"), key))
        self.db.execute(
            "INSERT OR IGNORE INTO objects "
            "(source_key,kind,source,source_digest,author_id,trusted,payload,payload_digest,parent_key,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, kind, json.dumps(source), expected[0], author_id, trusted,
             json.dumps(payload), expected[1], parent, source.get("created_at"), source.get("updated_at")),
        )

    def provenance(self, plane_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT author_id,trusted,payload_digest,source_key FROM objects "
            "WHERE plane_id=? AND status='complete'", (plane_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(zip(("source_author_id", "trusted", "payload_digest", "source_key"), row))

    def write_provenance(self) -> Path:
        """Publish confirmed source identities with an exact imported-text digest."""
        output = Path(self.db.execute("PRAGMA database_list").fetchone()[2]).parent / "provenance.json"
        entries = {}
        for plane_id, author_id, payload, human_thread in self.db.execute(
            "SELECT o.plane_id,o.author_id,o.payload,g.human_thread FROM objects o "
            "LEFT JOIN origins g ON g.source_key=COALESCE(o.parent_key,o.source_key) WHERE o.status='complete'"
        ):
            record = json.loads(payload)
            fields = {field: record.get(field) for field in ("name", "description_html", "comment_html")}
            entries[plane_id] = {
                "original_account_id": f"github:{author_id}" if author_id else None,
                "human_thread": human_thread != 0,
                "text_sha256": hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest(),
            }
        fd, temporary = tempfile.mkstemp(dir=output.parent, prefix=".provenance-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(entries, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output)
            directory_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return output

    def summary(self) -> dict:
        """Return counts only, never source content or attachment URLs."""
        return {"objects": dict(self.db.execute("SELECT status,count(*) FROM objects GROUP BY status")),
                "outcomes": dict(self.db.execute("SELECT kind || \":\" || status,count(*) FROM outcomes GROUP BY kind,status"))}

    def import_pending(self, create: Callable[[str, dict, str | None], dict], update: Callable | None = None):
        """Record intent before each write and stop rather than retry ambiguous results."""
        if self.db.execute("SELECT 1 FROM objects WHERE status='pending'").fetchone():
            raise MigrationError("Unconfirmed write requires remote reconciliation; retry blocked")
        rows = self.db.execute(
            "SELECT source_key,kind,payload,parent_key,status,plane_id FROM objects "
            "WHERE status IN ('planned','planned_update') ORDER BY CASE kind WHEN 'issue' THEN 0 ELSE 1 END, source_key"
        ).fetchall()
        for key, kind, payload, parent, status, destination in rows:
            if status == "planned_update" and update is None:
                raise MigrationError("Delta reconciliation requires an update writer")
            parent_id = None
            if parent:
                parent_row = self.db.execute(
                    "SELECT plane_id FROM objects WHERE source_key=? AND status='complete'", (parent,)
                ).fetchone()
                if not parent_row:
                    raise MigrationError("Parent issue has no confirmed destination")
                parent_id = parent_row[0]
            with self.db:
                changed = self.db.execute(
                    "UPDATE objects SET status='pending' WHERE source_key=? AND status=?", (key, status)
                ).rowcount
            if changed != 1:
                raise MigrationError("Another importer owns this write")
            try:
                if destination:
                    old_payload = json.loads(self.db.execute(
                        "SELECT payload FROM revisions WHERE source_key=? ORDER BY revision DESC LIMIT 1", (key,)
                    ).fetchone()[0])
                    result = update(kind, json.loads(payload), parent_id, destination, old_payload)
                else:
                    result = create(kind, json.loads(payload), parent_id)
                plane_id = str(UUID(result["id"]))
                with self.db:
                    if destination and plane_id != destination:
                        raise MigrationError("Delta update returned a different destination")
                    self.db.execute("INSERT INTO destinations VALUES (?,?) ON CONFLICT(plane_id) DO UPDATE SET record=excluded.record", (plane_id, json.dumps(result)))
                    self.db.execute("UPDATE objects SET status='complete',plane_id=? WHERE source_key=?",
                                    (plane_id, key))
            except Exception as error:
                raise MigrationError("Write result unconfirmed; reconcile remotely before retry") from error
            self.write_provenance()


def prepare(snapshot: dict, ledger: Ledger, trusted_ids: frozenset[str],
            issue_numbers: set[int], states: dict[str, str],
            labels_map: dict[str, str] | None = None, reconcile: bool = False) -> dict:
    """Plan an explicitly selected subset without printing original ticket text."""
    if snapshot.get("version") != 1 or not issue_numbers:
        raise MigrationError("A versioned export and explicit issue subset are required")
    repository = snapshot["repository"]
    labels_map = labels_map or {}
    found = set()
    with ledger.db:
        ledger.db.execute("BEGIN IMMEDIATE")
        for record in snapshot["records"]:
            issue = record["issue"]
            number = issue["number"]
            if number not in issue_numbers:
                continue
            found.add(number)
            labels = [label["name"] for label in issue.get("labels", [])]
            priorities = [name.removeprefix("Priority: ").lower() for name in labels if name.startswith("Priority: ")]
            if len(priorities) != 1 or priorities[0] not in {"high", "medium", "low"}:
                raise MigrationError("Selected issue needs exactly one supported priority")
            author_id = (issue.get("user") or {}).get("id")
            human_thread = "human" in labels or str(author_id) not in trusted_ids
            if human_thread and "human" not in labels:
                labels.append("human")
            required_labels = {label for label in labels if not label.startswith("Priority: ")}
            if not required_labels.issubset(labels_map):
                raise MigrationError("Every source label and origin restriction requires an explicit destination mapping")
            state = issue.get("state")
            reason = issue.get("state_reason")
            if state not in {"open", "closed"} or reason not in {None, "completed", "not_planned", "reopened"}:
                raise MigrationError("Source state needs explicit reconciliation")
            state_key = "open" if state == "open" else "cancelled" if reason == "not_planned" else "completed"
            if state_key not in states:
                raise MigrationError("Explicit destination state mapping is missing")
            key = f"github:{repository}:issue:{issue['id']}"
            body = issue.get("body") or ""
            payload = {"name": issue["title"], "description_html": f"<pre>{html.escape(body)}</pre>",
                       "priority": priorities[0], "state": states[state_key]}
            payload["labels"] = [labels_map[name] for name in labels if name in labels_map and not name.startswith("Priority: ")]
            ledger.record(key, "issue", issue, payload, trusted_ids, reconcile=reconcile)
            ledger.db.execute("INSERT INTO origins VALUES (?,?) ON CONFLICT(source_key) DO UPDATE SET human_thread=MAX(origins.human_thread,excluded.human_thread)",
                              (key, int(human_thread)))
            for label in labels:
                if not label.startswith("Priority: "):
                    ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)",
                                      (key, "label", label, "mapped" if label in labels_map else "not_mapped"))
            source_comments = {f"github:{repository}:comment:{comment['id']}" for comment in record["comments"]}
            previous_comments = {row[0] for row in ledger.db.execute("SELECT source_key FROM objects WHERE parent_key=?", (key,))}
            if previous_comments - source_comments:
                raise MigrationError("Source comments were deleted; explicit archival reconciliation required")
            for comment in record["comments"]:
                comment_key = f"github:{repository}:comment:{comment['id']}"
                comment_body = comment.get("body") or ""
                ledger.record(comment_key, "comment", comment,
                              {"comment_html": f"<pre>{html.escape(comment_body)}</pre>"}, trusted_ids, key, reconcile=reconcile)
                body += "\n" + comment_body
            for url in re.findall(r"https://(?:github\.com/user-attachments/|user-images\.githubusercontent\.com/)[^\s<>\)\]]+", body):
                ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)",
                                  (key, "attachment", url, "not_copied"))
            ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)",
                              (key, "timeline", json.dumps(record["timeline"], sort_keys=True), "not_reconciled"))
        if found != issue_numbers:
            raise MigrationError("Selected issue is absent from the export")
    return ledger.summary()


def rehearsal_writer(project_id: str, settings=None, transport=None, labels_map=None):
    """Bind writes to an explicitly configured disposable project and importer account."""
    from tools.plane.client import Client, Transport
    from tools.plane.policy import PlaneError, Settings, private_json, uuid

    if settings is None:
        config = private_json(os.environ["WISH_PLANE_CONFIG"])
        if config.get("rehearsal_project_id") != project_id:
            raise MigrationError("Configuration must explicitly identify the rehearsal project")
        settings = Settings(config)
    if settings.project != project_id or not settings.writes_enabled or not settings.importers:
        raise MigrationError("Rehearsal scope, writes and importer identities must be configured")
    transport = transport or Transport(settings)
    try:
        identity = uuid(transport.request("GET", "users/me")["id"])
        if identity not in settings.importers:
            raise MigrationError("Rehearsal token must belong to a configured importer")
    except (PlaneError, KeyError, TypeError) as error:
        raise MigrationError("Importer identity could not be verified") from error
    items = f"workspaces/{settings.workspace}/projects/{settings.project}/{settings.resource}"
    if labels_map is not None:
        client = Client(settings, transport)
        live_labels = {record["id"]: record["name"] for record in client.pages(f"{client.prefix}/labels")}
        if any(live_labels.get(value) != name for name, value in labels_map.items()):
            raise MigrationError("Destination label IDs do not match their required source meanings")

    def create(kind, payload, parent_id, destination=None, old_payload=None):
        try:
            path = items if kind == "issue" else f"{items}/{uuid(parent_id)}/comments"
            if destination:
                before = transport.request("GET", f"{path}/{uuid(destination)}")
                for field, expected in old_payload.items():
                    actual = before.get(field)
                    if field == "state" and isinstance(actual, dict):
                        actual = actual.get("id")
                    if field == "labels" and isinstance(actual, list):
                        actual = sorted(value.get("id") if isinstance(value, dict) else value for value in actual)
                        expected = sorted(expected)
                    if actual != expected:
                        raise MigrationError("Destination changed independently; delta update blocked")
                result = transport.request("PATCH", f"{path}/{uuid(destination)}", data=payload)
            else:
                result = transport.request("POST", path, data=payload)
            record_id = uuid(result["id"])
            readback = transport.request("GET", f"{path}/{record_id}")
            creator = readback.get("created_by")
            creator = creator.get("id") if isinstance(creator, dict) else creator
            if uuid(readback["id"]) != record_id or uuid(creator) != identity:
                raise MigrationError("Imported record authorship did not match")
            if readback.get("project") and uuid(readback["project"]) != project_id:
                raise MigrationError("Imported record project did not match")
            for field, expected in payload.items():
                actual = readback.get(field)
                if field == "state" and isinstance(actual, dict):
                    actual = actual.get("id")
                if field == "labels" and isinstance(actual, list):
                    actual = sorted(value.get("id") if isinstance(value, dict) else value for value in actual)
                    expected = sorted(expected)
                if actual != expected:
                    raise MigrationError("Imported content did not match its private source")
            issue_id = record_id if kind == "issue" else parent_id
            readback["_migration_url"] = f"{settings.base_url}/{settings.workspace}/projects/{project_id}/issues/{issue_id}"
            return readback
        except (PlaneError, KeyError, TypeError, ValueError) as error:
            raise MigrationError("Rehearsal write or readback failed") from error

    return create


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--directory", type=Path, required=True)
    export.add_argument("--repository", required=True)
    rehearsal = sub.add_parser("rehearse")
    rehearsal.add_argument("--directory", type=Path, required=True)
    rehearsal.add_argument("--snapshot", type=Path, required=True)
    rehearsal.add_argument("--rehearsal-project", required=True)
    rehearsal.add_argument("--issue", type=int, action="append", required=True)
    rehearsal.add_argument("--trusted-github-id", type=int, action="append", default=[])
    rehearsal.add_argument("--state-open", required=True)
    rehearsal.add_argument("--state-completed")
    rehearsal.add_argument("--state-cancelled")
    rehearsal.add_argument("--label-map-file", type=Path)
    rehearsal.add_argument("--allow-writes", action="store_true")
    rehearsal.add_argument("--reconcile-delta", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            export_source(args.directory, args.repository)
            print("Export complete; private source text withheld")
            return 0
        info = args.snapshot.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise MigrationError("Export must be a private file owned by this account")
        project = str(UUID(args.rehearsal_project))
        states = {key: str(UUID(value)) for key, value in {
            "open": args.state_open, "completed": args.state_completed,
            "cancelled": args.state_cancelled,
        }.items() if value}
        labels_map = json.loads(args.label_map_file.read_text()) if args.label_map_file else {}
        labels_map = {name: str(UUID(value)) for name, value in labels_map.items()}
        ledger = Ledger(args.directory, project)
        try:
            prepare(json.loads(args.snapshot.read_text()), ledger,
                    frozenset(str(value) for value in args.trusted_github_id), set(args.issue), states, labels_map, reconcile=args.reconcile_delta)
            if args.allow_writes:
                writer = rehearsal_writer(project, labels_map=labels_map)
                ledger.import_pending(writer, update=writer)
            ledger.write_provenance()
            print("Rehearsal counts: " + json.dumps(ledger.summary(), sort_keys=True))
        finally:
            ledger.close()
        return 0
    except Exception:
        print("Migration failed; source output withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
