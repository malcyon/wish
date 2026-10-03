"""Reconcile exported GitHub dependencies with the pinned Plane relation API."""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from uuid import UUID

from tools.plane.policy import PlaneError


class RelationError(PlaneError):
    """Report a dependency failure without including source ticket text."""


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS relations (
        source_key TEXT NOT NULL, target_key TEXT NOT NULL,
        kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
        PRIMARY KEY (source_key,target_key,kind)
    )""")


def plan(db, source_key, dependencies, repository):
    """Preserve native dependency direction and detect removals during delta export."""
    targets = set()
    for dependency in dependencies:
        source_id = dependency.get("id")
        if type(source_id) is not int or source_id < 1:
            raise RelationError("Dependency is missing its stable source ID")
        repository_url = dependency.get("repository_url", f"https://api.github.com/repos/{repository}")
        parsed = urlsplit(repository_url)
        components = parsed.path.strip("/").split("/")
        if parsed.scheme != "https" or parsed.netloc != "api.github.com" or len(components) != 3 or components[0] != "repos":
            raise RelationError("Dependency repository scope is invalid")
        targets.add(f"github:{components[1]}/{components[2]}:issue:{source_id}")
    existing = dict(db.execute("SELECT target_key,status FROM relations WHERE source_key=? AND kind='blocked_by'", (source_key,)))
    for target, status in existing.items():
        if target not in targets:
            db.execute("UPDATE relations SET status=? WHERE source_key=? AND target_key=? AND kind='blocked_by'",
                       ("removed" if status not in {"planned", "omitted"} else "omitted", source_key, target))
    for target in targets:
        if target == source_key:
            raise RelationError("A source issue cannot block itself")
        db.execute("INSERT INTO relations VALUES (?,?,'blocked_by','planned') ON CONFLICT(source_key,target_key,kind) DO UPDATE SET status=CASE WHEN relations.status='omitted' THEN 'planned' ELSE relations.status END",
                   (source_key, target))


def _destination(db, key):
    row = db.execute("SELECT plane_id FROM objects WHERE source_key=? AND kind='issue' AND status='complete'", (key,)).fetchone()
    if row is None:
        raise RelationError("A dependency endpoint has not been imported; include it in the explicit subset")
    return str(UUID(row[0]))


def _contains(result, kind, target, project):
    if not isinstance(result, dict) or kind not in result:
        raise RelationError("Plane returned incomplete relation readback")
    for entries in result.values():
        if not isinstance(entries, list):
            raise RelationError("Plane returned invalid relation readback")
        for entry in entries:
            if not isinstance(entry, dict) or "issue_id" not in entry or "project_id" not in entry:
                raise RelationError("Plane returned invalid relation endpoint IDs")
            UUID(entry["issue_id"])
            UUID(entry["project_id"])
    matching = {name for name, entries in result.items() if any(
        entry["issue_id"] == target and entry["project_id"] == project for entry in entries
    )}
    if matching - {kind}:
        raise RelationError("A different destination relation already connects these issues")
    return kind in matching


def reconcile(ledger, transport, settings):
    """Create each missing dependency once and confirm the forward and reverse links."""
    if settings.project != ledger.project_id or settings.resource != "work-items" or not settings.writes_enabled:
        raise RelationError("Dependency migration requires the scoped work-items API")
    if ledger.db.execute("SELECT 1 FROM relations WHERE status='removed'").fetchone():
        raise RelationError("A migrated source dependency was removed; the pinned public API cannot delete it")
    if transport.request("GET", "users/me").get("id") not in settings.importers:
        raise RelationError("Dependency token must belong to the configured importer")
    prefix = f"workspaces/{settings.workspace}/projects/{settings.project}/work-items"
    rows = ledger.db.execute("SELECT source_key,target_key,kind,status FROM relations WHERE status!='omitted' ORDER BY source_key,target_key").fetchall()
    for source, target, kind, stage in rows:
        source_id, target_id = _destination(ledger.db, source), _destination(ledger.db, target)
        path = f"{prefix}/{source_id}/relations"
        reverse_path = f"{prefix}/{target_id}/relations"

        def verified():
            direct = _contains(transport.request("GET", path), kind, target_id, settings.project)
            reverse = _contains(transport.request("GET", reverse_path), "blocking", source_id, settings.project)
            if direct != reverse:
                raise RelationError("Dependency readback disagrees between its endpoints")
            return direct

        if verified():
            with ledger.db:
                ledger.db.execute("UPDATE relations SET status='complete' WHERE source_key=? AND target_key=? AND kind=?", (source, target, kind))
            continue
        if stage != "planned":
            raise RelationError("Dependency write outcome is unconfirmed; automatic replay blocked")
        with ledger.db:
            count = ledger.db.execute("UPDATE relations SET status='pending' WHERE source_key=? AND target_key=? AND kind=? AND status='planned'", (source, target, kind)).rowcount
        if count != 1:
            raise RelationError("Another importer owns this dependency write")
        transport.request("POST", path, data={"relation_type": kind, "issues": [target_id]})
        if not verified():
            raise RelationError("Dependency creation was not confirmed by readback")
        with ledger.db:
            ledger.db.execute("UPDATE relations SET status='complete' WHERE source_key=? AND target_key=? AND kind=?", (source, target, kind))


def counts(db):
    """Expose dependency counts without printing source records."""
    return dict(db.execute("SELECT status,count(*) FROM relations GROUP BY status"))


def archive_dependency_metadata(db, key, dependencies):
    """Keep the original dependency records alongside the imported relation IDs."""
    db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?)", (key, "dependencies", json.dumps(dependencies, sort_keys=True), "preserved"))
