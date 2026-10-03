#!/usr/bin/env python3
"""Export GitHub history privately and import tickets with durable provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Callable
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


EXCLUDED_LABELS = frozenset({"ai", "human"})
STATE_GROUPS = {"Backlog": "backlog", "Queue": "unstarted", "In Progress": "started", "Completed": "completed"}


class MigrationError(Exception):
    """Report a migration failure without exposing source text or credentials."""


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()



@lru_cache(maxsize=1)
def markdown_renderer():
    """Load the pinned renderer with raw HTML disabled for public source text."""
    if version("markdown-it-py") != "3.0.0":
        raise MigrationError("Install the pinned markdown-it-py==3.0.0 migration dependency")
    from markdown_it import MarkdownIt

    renderer = MarkdownIt("js-default")

    def link_open(self, tokens, index, options, env):
        tokens[index].attrSet("rel", "noopener noreferrer")
        return self.renderToken(tokens, index, options, env)

    renderer.add_render_rule("link_open", link_open)
    return renderer


def render_markdown(source: str) -> str:
    """Render safe headings, lists, links, code and tables inside one HTML root."""
    return "<div>" + markdown_renderer().render(source) + "</div>"


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


@contextmanager
def operation_lock(path: Path):
    """Exclude concurrent imports and backups sharing this service-side lock file."""
    if sys.platform != "linux":
        raise MigrationError("Migration writes require the Linux service-side backup lock")
    import fcntl

    private_directory(path.parent)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode):
            raise MigrationError("Migration lock must be an owner-only regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MigrationError("Another migration or backup holds the service-state lock") from error
        yield
    finally:
        os.close(descriptor)


def sync_directory(directory: Path):
    """Make marker creation and removal durable before releasing the backup lock."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def migration_marker(directory: Path, enabled: bool):
    """Keep backups blocked after an interrupted write until a successful resume."""
    if not enabled:
        yield
        return
    directory = private_directory(directory)
    marker = directory / ".migration-in-progress"
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode):
            raise MigrationError("Migration marker must be an owner-only regular file")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    sync_directory(directory)
    yield
    marker.unlink()
    sync_directory(directory)


def github_pages(endpoint: str) -> list[dict]:
    """Capture all API pages without exposing GitHub text on either output stream."""
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", "--paginate", endpoint],
            capture_output=True, text=True, timeout=300, check=True,
        )
        decoder = json.JSONDecoder()
        remaining = result.stdout.lstrip()
        items = []
        if not remaining:
            raise ValueError
        while remaining:
            page, end = decoder.raw_decode(remaining)
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise ValueError
            items.extend(page)
            remaining = remaining[end:].lstrip()
        return items
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
                        "timeline": fetch(f"{prefix}/timeline?per_page=100"),
                        "blocked_by": fetch(f"{prefix}/dependencies/blocked_by?per_page=100")})
    snapshot = {"version": 2, "repository": repository,
                "exported_at": datetime.now(UTC).isoformat(), "records": records,
                "limitations": ["Attachment bytes have not been downloaded",
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
            CREATE TABLE IF NOT EXISTS service_scope (origin TEXT, workspace TEXT, project TEXT);
            CREATE TABLE IF NOT EXISTS run_mode (mode TEXT PRIMARY KEY);
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
            CREATE TABLE IF NOT EXISTS body_overrides (
                source_key TEXT PRIMARY KEY, source_body_digest TEXT NOT NULL,
                editor_id TEXT NOT NULL, plane_id TEXT NOT NULL,
                markdown TEXT NOT NULL, readback TEXT NOT NULL, captured_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                source_key TEXT NOT NULL, kind TEXT NOT NULL,
                detail TEXT NOT NULL, status TEXT NOT NULL,
                UNIQUE(source_key, kind, detail)
            );
        """)
        from tools.plane import attachments, relations
        attachments.initialize(self.db)
        relations.initialize(self.db)
        self.db.execute("BEGIN IMMEDIATE")
        scopes = self.db.execute("SELECT project FROM scope").fetchall()
        if scopes and scopes != [(project_id,)]:
            self.db.close()
            raise MigrationError("Ledger belongs to a different Plane project")
        self.db.execute("INSERT OR IGNORE INTO scope VALUES (?)", (project_id,))
        self.db.commit()
        self.project_id = project_id

    def bind_service(self, settings, production=False):
        """Keep a migration ledger tied to the exact origin, workspace and project."""
        expected = (settings.base_url, settings.workspace, settings.project)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT origin,workspace,project FROM service_scope").fetchall()
            if existing and existing != [expected]:
                raise MigrationError("Ledger belongs to a different Plane service or workspace")
            if not existing:
                self.db.execute("INSERT INTO service_scope VALUES (?,?,?)", expected)
            mode = "production" if production else "rehearsal"
            modes = self.db.execute("SELECT mode FROM run_mode").fetchall()
            if modes and modes != [(mode,)]:
                raise MigrationError("Production and rehearsal require separate ledgers")
            if not modes:
                self.db.execute("INSERT INTO run_mode VALUES (?)", (mode,))

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

    def issue_body(self, key: str, source: dict) -> str:
        """Preserve a confirmed Plane edit until an overlapping source change is resolved."""
        body = source.get("body") or ""
        override = self.db.execute(
            "SELECT source_body_digest,markdown FROM body_overrides WHERE source_key=?", (key,)
        ).fetchone()
        if override is None:
            return body
        if override[0] != digest(body):
            raise MigrationError("GitHub body changed after a preserved Plane edit; manual reconciliation required")
        return override[1]

    def preserve_body_edit(self, key: str, readback: dict, settings, apply: bool = True):
        """Confirm one imported issue while preserving its trusted editor's current Markdown."""
        from tools.plane.client import HTMLContent, confirm_changes
        from tools.plane.policy import uuid

        row = self.db.execute(
            "SELECT source,payload,source_digest,author_id,trusted,status,plane_id,kind FROM objects WHERE source_key=?",
            (key,),
        ).fetchone()
        if row is None or row[7] != "issue" or row[5] not in {"pending", "complete"}:
            raise MigrationError("Body edit recovery requires a pending or confirmed imported issue")
        creator = readback.get("created_by")
        creator = creator.get("id") if isinstance(creator, dict) else creator
        editor = readback.get("updated_by")
        editor = editor.get("id") if isinstance(editor, dict) else editor
        plane_id = uuid(readback.get("id"))
        if (self.project_id != settings.project or readback.get("project") != settings.project
                or creator not in settings.importers or editor not in settings.trusted
                or editor in settings.importers or row[6] not in {None, plane_id}):
            raise MigrationError("Body edit recovery requires the expected project, importer and trusted editor")
        payload = json.loads(row[1])
        confirm_changes(readback, {field: value for field, value in payload.items() if field != "description_html"})
        current = readback.get("description_html")
        if not isinstance(current, str):
            raise MigrationError("Body edit recovery requires a confirmed HTML description")
        events = HTMLContent(current).events
        structure = [(event[0], event[1]) if event[0] != "data" else ("data",) for event in events]
        direct = [("start", "pre"), ("data",), ("end", "pre")]
        code = [("start", "pre"), ("start", "code"), ("data",), ("end", "code"), ("end", "pre")]
        empty_paragraph = [("start", "p"), ("end", "p")]
        if structure not in (direct, code, direct + empty_paragraph, code + empty_paragraph):
            raise MigrationError("Body edit recovery only accepts literal Markdown in the existing code block")
        markdown = next(event[1] for event in events if event[0] == "data")
        source = json.loads(row[0])
        expected = (digest(source.get("body") or ""), uuid(editor), plane_id, markdown, json.dumps(readback, sort_keys=True))
        previous = self.db.execute(
            "SELECT source_body_digest,editor_id,plane_id,markdown,readback FROM body_overrides WHERE source_key=?", (key,)
        ).fetchone()
        if previous is not None:
            if previous != expected:
                raise MigrationError("A different preserved Plane edit already exists")
            return
        if not apply:
            return
        captured = datetime.now(UTC).isoformat()
        with self.db:
            self.db.execute("INSERT INTO body_overrides VALUES (?,?,?,?,?,?,?)", (key, *expected, captured))
            self.db.execute("INSERT INTO revisions (source_key,source,payload,source_digest,author_id,trusted,captured_at) VALUES (?,?,?,?,?,?,?)",
                            (key, *row[:5], captured))
            payload["description_html"] = current
            self.db.execute("INSERT INTO destinations VALUES (?,?) ON CONFLICT(plane_id) DO UPDATE SET record=excluded.record",
                            (plane_id, json.dumps(readback)))
            self.db.execute("UPDATE objects SET status='complete',plane_id=?,payload=?,payload_digest=? WHERE source_key=?",
                            (plane_id, json.dumps(payload), digest(payload), key))
        self.write_provenance()

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
        for plane_id, author_id, readback, human_thread, kind in self.db.execute(
            "SELECT o.plane_id,o.author_id,d.record,g.human_thread,o.kind FROM objects o "
            "JOIN destinations d ON d.plane_id=o.plane_id "
            "LEFT JOIN origins g ON g.source_key=COALESCE(o.parent_key,o.source_key) WHERE o.status='complete'"
        ):
            record = json.loads(readback)
            required = ("name", "description_html") if kind == "issue" else ("comment_html",)
            if any(not isinstance(record.get(field), str) for field in required):
                continue
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
        from tools.plane import attachments, relations
        return {"objects": dict(self.db.execute("SELECT status,count(*) FROM objects GROUP BY status")),
                "attachments": attachments.counts(self.db), "relations": relations.counts(self.db),
                "outcomes": dict(self.db.execute("SELECT kind || \":\" || status,count(*) FROM outcomes GROUP BY kind,status"))}

    def import_pending(self, create: Callable[[str, dict, str | None], dict], update: Callable | None = None):
        """Record intent before each write and stop rather than retry ambiguous results."""
        if self.db.execute("SELECT 1 FROM objects WHERE status='pending'").fetchone():
            raise MigrationError("Unconfirmed write requires remote reconciliation; retry blocked")
        rows = self.db.execute(
            "SELECT source_key,kind,payload,parent_key,status,plane_id FROM objects "
            "WHERE status IN ('planned','planned_update') ORDER BY CASE kind WHEN 'issue' THEN 0 ELSE 1 END, "
            "CASE json_extract(source,'$.state') WHEN 'open' THEN 0 ELSE 1 END, created_at, source_key"
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
            labels_map: dict[str, str] | None = None, reconcile: bool = False,
            default_priority: str | None = None) -> dict:
    """Plan an explicitly selected subset without printing original ticket text."""
    if snapshot.get("version") not in {1, 2} or not issue_numbers:
        raise MigrationError("A versioned export and explicit issue subset are required")
    from tools.plane import attachments, relations
    repository = snapshot["repository"]
    labels_map = labels_map or {}
    if any(name.casefold() in EXCLUDED_LABELS for name in labels_map):
        raise MigrationError("AI and human labels must not be recreated in Plane")
    if default_priority not in {None, "none", "high", "medium", "low"}:
        raise MigrationError("Invalid explicit fallback priority")
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
            if not priorities and default_priority is not None:
                priority = default_priority
            elif len(priorities) == 1 and priorities[0] in {"high", "medium", "low"}:
                priority = priorities[0]
            else:
                raise MigrationError("Selected issue needs one supported priority or an explicit fallback for a missing priority")
            author_id = (issue.get("user") or {}).get("id")
            human_thread = any(label.casefold() == "human" for label in labels) or str(author_id) not in trusted_ids
            required_labels = {label for label in labels if label.casefold() not in EXCLUDED_LABELS}
            if not required_labels.issubset(labels_map):
                raise MigrationError("Every source label except AI and human requires an explicit destination mapping")
            state = issue.get("state")
            reason = issue.get("state_reason")
            if state not in {"open", "closed"} or reason not in {None, "completed", "not_planned", "reopened"}:
                raise MigrationError("Source state needs explicit reconciliation")
            state_key = "open" if state == "open" else "cancelled" if reason == "not_planned" else "completed"
            if state_key not in states:
                raise MigrationError("Explicit destination state mapping is missing")
            key = f"github:{repository}:issue:{issue['id']}"
            body = ledger.issue_body(key, issue)
            payload = {"name": issue["title"], "description_html": render_markdown(body),
                       "priority": priority, "state": states[state_key]}
            payload["labels"] = [labels_map[name] for name in labels if name.casefold() not in EXCLUDED_LABELS]
            ledger.record(key, "issue", issue, payload, trusted_ids, reconcile=reconcile)
            attachments.note_sources(ledger.db, key, key, issue)
            ledger.db.execute("INSERT INTO origins VALUES (?,?) ON CONFLICT(source_key) DO UPDATE SET human_thread=MAX(origins.human_thread,excluded.human_thread)",
                              (key, int(human_thread)))
            for label in labels:
                ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)",
                                  (key, "label", label, "excluded" if label.casefold() in EXCLUDED_LABELS else "mapped"))
            if not priorities:
                ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)", (key, "priority", priority, "explicit_fallback"))
            source_comments = {f"github:{repository}:comment:{comment['id']}" for comment in record["comments"]}
            previous_comments = {row[0] for row in ledger.db.execute("SELECT source_key FROM objects WHERE parent_key=?", (key,))}
            if previous_comments - source_comments:
                raise MigrationError("Source comments were deleted; explicit archival reconciliation required")
            for comment in record["comments"]:
                comment_key = f"github:{repository}:comment:{comment['id']}"
                comment_body = comment.get("body") or ""
                ledger.record(comment_key, "comment", comment,
                              {"comment_html": render_markdown(comment_body)}, trusted_ids, key, reconcile=reconcile)
                attachments.note_sources(ledger.db, key, comment_key, comment)
                body += "\n" + comment_body
            attachments.plan(ledger.db, key, attachments.discover(body))
            ledger.db.execute("DELETE FROM outcomes WHERE source_key=? AND kind='attachment'", (key,))
            if snapshot["version"] == 2:
                relations.plan(ledger.db, key, record["blocked_by"], repository)
                relations.archive_dependency_metadata(ledger.db, key, record["blocked_by"])
            ledger.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)",
                              (key, "timeline", json.dumps(record["timeline"], sort_keys=True), "preserved"))
        if found != issue_numbers:
            raise MigrationError("Selected issue is absent from the export")
    return ledger.summary()


def migration_writer(project_id: str, settings=None, transport=None, labels_map=None,
                     production=False, state_definitions=None):
    """Bind writes to a separately authorized project mode and importer account."""
    from tools.plane.client import Client, HTMLContent, Transport
    from tools.plane.policy import PlaneError, Settings, private_json, uuid

    config = None
    if settings is None:
        config = private_json(os.environ["WISH_PLANE_CONFIG"])
        scope_key = "import_project_id" if production else "rehearsal_project_id"
        if config.get(scope_key) != project_id:
            raise MigrationError("Configuration must explicitly identify the selected import project mode")
        if production and config.get("import_enabled") is not True:
            raise MigrationError("Production imports require explicit import_enabled configuration")
        other_key = "rehearsal_project_id" if production else "import_project_id"
        if config.get(other_key) == project_id:
            raise MigrationError("Production and rehearsal projects must be distinct")
        settings = Settings(config)
    if settings.resource != "work-items":
        raise MigrationError("Migration requires the pinned work-items API for dependencies and attachments")
    if settings.project != project_id or not settings.writes_enabled or not settings.importers:
        raise MigrationError("Migration scope, writes and importer identities must be configured")
    transport = transport or Transport(settings)
    try:
        identity = uuid(transport.request("GET", "users/me")["id"])
        if identity not in settings.importers:
            raise MigrationError("Migration token must belong to a configured importer")
    except (PlaneError, KeyError, TypeError) as error:
        raise MigrationError("Importer identity could not be verified") from error
    items = f"workspaces/{settings.workspace}/projects/{settings.project}/{settings.resource}"
    client = Client(settings, transport)
    if labels_map is not None:
        if any(name.casefold() in EXCLUDED_LABELS for name in labels_map):
            raise MigrationError("AI and human labels must not be recreated in Plane")
        live_labels = {record["id"]: record["name"] for record in client.pages(f"{client.prefix}/labels")}
        if any(live_labels.get(value) != name for name, value in labels_map.items()):
            raise MigrationError("Destination label IDs do not match their required source meanings")

    if state_definitions is not None:
        if set(state_definitions) != set(STATE_GROUPS):
            raise MigrationError("State mapping must contain exactly Backlog, Queue, In Progress and Completed")
        live_states = {record["id"]: record for record in client.pages(f"{client.prefix}/states")}
        for name, identifier in state_definitions.items():
            state = live_states.get(identifier, {})
            if state.get("name") != name or state.get("group") != STATE_GROUPS[name]:
                raise MigrationError("Destination state IDs do not match the authorized names and workflow groups")

    def same_content(field, actual, expected):
        if field in {"description_html", "comment_html"}:
            return (isinstance(actual, str) and isinstance(expected, str)
                    and HTMLContent(actual).events == HTMLContent(expected).events)
        return actual == expected

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
                    if not same_content(field, actual, expected):
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
                if not same_content(field, actual, expected):
                    raise MigrationError("Imported content did not match its private source")
            issue_id = record_id if kind == "issue" else parent_id
            readback["_migration_url"] = f"{settings.base_url}/{settings.workspace}/projects/{project_id}/issues/{issue_id}"
            return readback
        except (PlaneError, KeyError, TypeError, ValueError) as error:
            raise MigrationError("Migration write or readback failed") from error

    create.settings = settings
    create.transport = transport
    create.config = config
    return create


def select_issues(snapshot, scope, explicit):
    """Select open work before history and include its native dependency closure."""
    records = snapshot["records"]
    by_number = {record["issue"]["number"]: record for record in records}
    by_id = {record["issue"]["id"]: record for record in records}
    if len(by_number) != len(records) or len(by_id) != len(records):
        raise MigrationError("Source export contains duplicate issue identities")
    if scope == "selected":
        if not explicit:
            raise MigrationError("Selected scope requires explicit issue numbers")
        selected = set(explicit)
    else:
        if explicit:
            raise MigrationError("Explicit issue numbers require selected scope")
        selected = {number for number, record in by_number.items() if scope == "all" or
                    (scope == "open" and record["issue"]["state"] == "open") or
                    (scope == "history" and record["issue"]["state"] == "closed")}
    if selected - by_number.keys():
        raise MigrationError("Selected issue is absent from the export")
    pending = list(selected)
    while pending:
        number = pending.pop()
        for dependency in by_number[number].get("blocked_by", []):
            expected_repo = f"https://api.github.com/repos/{snapshot['repository']}"
            if dependency.get("repository_url", expected_repo) != expected_repo:
                raise MigrationError("A dependency belongs to another repository and requires an explicit source export")
            target = by_id.get(dependency["id"])
            if target is None:
                raise MigrationError("A dependency is missing from the full source export")
            target_number = target["issue"]["number"]
            if target_number not in selected:
                selected.add(target_number)
                pending.append(target_number)
    return selected


def main(argv=None) -> int:
    from tools.plane.policy import PlaneError

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--directory", type=Path, required=True)
    export.add_argument("--repository", required=True)
    for command in ("rehearse", "import"):
        run = sub.add_parser(command)
        run.add_argument("--directory", type=Path, required=True)
        run.add_argument("--snapshot", type=Path, required=True)
        run.add_argument("--rehearsal-project" if command == "rehearse" else "--project", required=True)
        run.add_argument("--scope", choices=("selected", "open", "history", "all"), default="selected", required=command == "import")
        run.add_argument("--issue", type=int, action="append", default=[])
        run.add_argument("--trusted-github-id", type=int, action="append", default=[])
        run.add_argument("--state-map-file", type=Path, required=command == "import")
        run.add_argument("--open-state", choices=("Backlog", "Queue", "In Progress"), default="Backlog")
        run.add_argument("--state-open")
        run.add_argument("--state-completed")
        run.add_argument("--state-cancelled")
        run.add_argument("--label-map-file", type=Path, required=command == "import")
        run.add_argument("--default-priority", choices=("none", "high", "medium", "low"))
        run.add_argument("--allow-writes" if command == "rehearse" else "--allow-import", action="store_true")
        run.add_argument("--reconcile-delta", action="store_true")
        run.add_argument("--lock-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            export_source(args.directory, args.repository)
            print("Export complete; private source text withheld")
            return 0
        production = args.command == "import"
        allow_writes = args.allow_import if production else args.allow_writes
        info = args.snapshot.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise MigrationError("Export must be a private file owned by this account")
        project = str(UUID(args.project if production else args.rehearsal_project))
        definitions = None
        if args.state_map_file:
            if any((args.state_open, args.state_completed, args.state_cancelled)):
                raise MigrationError("Use either the named state map or individual state IDs")
            definitions = {name: str(UUID(value)) for name, value in json.loads(args.state_map_file.read_text()).items()}
            if set(definitions) != set(STATE_GROUPS):
                raise MigrationError("State mapping must contain exactly the four authorized states")
            states = {"open": definitions[args.open_state], "completed": definitions["Completed"], "cancelled": definitions["Completed"]}
        else:
            states = {key: str(UUID(value)) for key, value in {
                "open": args.state_open, "completed": args.state_completed, "cancelled": args.state_cancelled,
            }.items() if value}
        labels_map = json.loads(args.label_map_file.read_text()) if args.label_map_file else {}
        labels_map = {name: str(UUID(value)) for name, value in labels_map.items()}
        source = json.loads(args.snapshot.read_text())
        if allow_writes and source.get("version") != 2:
            raise MigrationError("Live migration requires a fresh export containing native dependencies")
        selected = select_issues(source, args.scope, args.issue)
        if not selected:
            print("Migration counts: No source issues in the requested scope")
            return 0
        lock_file = args.lock_file or args.directory / "state.lock"
        if lock_file.absolute() != (args.directory / "state.lock").absolute():
            raise MigrationError("Migration and backup must share the state directory lock")
        with operation_lock(lock_file), migration_marker(args.directory, allow_writes):
            ledger = Ledger(args.directory, project)
            try:
                prepare(source, ledger, frozenset(str(value) for value in args.trusted_github_id),
                        selected, states, labels_map, reconcile=args.reconcile_delta,
                        default_priority=args.default_priority)
                if allow_writes:
                    writer = migration_writer(project, labels_map=labels_map, production=production,
                                              state_definitions=definitions)
                    settings, config = writer.settings, writer.config
                    if not {f"github:{value}" for value in args.trusted_github_id}.issubset(settings.source_trusted):
                        raise MigrationError("Migration source trust exceeds the configured source allowlist")
                    ledger.bind_service(settings, production=production)
                    ledger.import_pending(writer, update=writer)
                    from tools.plane import attachments, relations
                    attachments.transfer_all(ledger, attachments.Transfer(settings, config))
                    relations.reconcile(ledger, writer.transport, settings)
                ledger.write_provenance()
                print("Migration counts: " + json.dumps(ledger.summary(), sort_keys=True))
            finally:
                ledger.close()
        return 0
    except (MigrationError, PlaneError) as error:
        print(f"Migration stopped: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("Migration failed; source output withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
