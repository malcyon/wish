"""Exercise dependency direction, incomplete mappings and interrupted migration."""
import sqlite3
from types import SimpleNamespace

import pytest

from tools.plane.relations import RelationError, counts, initialize, plan, reconcile

PROJECT = "00000000-0000-0000-0000-000000000001"
FIRST = "00000000-0000-0000-0000-000000000002"
SECOND = "00000000-0000-0000-0000-000000000003"
IMPORTER = "00000000-0000-0000-0000-000000000004"
SOURCE = "github:owner/repo:issue:10"
TARGET = "github:owner/repo:issue:20"


@pytest.fixture
def ledger(tmp_path):
    # Relation-state tests use portable SQLite; private-file enforcement is tested separately.
    ledger = SimpleNamespace(db=sqlite3.connect(tmp_path / "ledger.sqlite3"), project_id=PROJECT)
    ledger.db.execute("CREATE TABLE objects (source_key TEXT PRIMARY KEY, kind TEXT, status TEXT, plane_id TEXT)")
    initialize(ledger.db)
    with ledger.db:
        for key, destination in ((SOURCE, FIRST), (TARGET, SECOND)):
            ledger.db.execute("INSERT INTO objects VALUES (?, 'issue', 'complete', ?)", (key, destination))
        plan(ledger.db, SOURCE, [{"id": 20}], "owner/repo")
    yield ledger
    ledger.db.close()


def settings():
    return SimpleNamespace(project=PROJECT, workspace="wish", resource="work-items",
                           writes_enabled=True, importers={IMPORTER})


class Transport:
    def __init__(self):
        self.kind = None
        self.posts = 0
        self.timeout = False
        self.save_before_timeout = True

    def request(self, method, path, data=None):
        if path == "users/me":
            return {"id": IMPORTER}
        if method == "POST":
            assert f"/{FIRST}/relations" in path
            assert data == {"relation_type": "blocked_by", "issues": [SECOND]}
            self.posts += 1
            if self.save_before_timeout:
                self.kind = "blocked_by"
            if self.timeout:
                raise TimeoutError
            return []
        result = {"blocking": [], "blocked_by": [], "relates_to": [], "duplicate": []}
        if self.kind:
            first = f"/{FIRST}/relations" in path
            kind = self.kind if first or self.kind != "blocked_by" else "blocking"
            result[kind] = [{"issue_id": SECOND if first else FIRST, "project_id": PROJECT}]
        return result


def test_native_dependency_direction_is_verified_and_idempotent(ledger):
    transport = Transport()
    reconcile(ledger, transport, settings())
    reconcile(ledger, transport, settings())
    assert transport.posts == 1
    assert counts(ledger.db) == {"complete": 1}


def test_relation_timeout_is_reconciled_without_duplicate_write(ledger):
    transport = Transport()
    transport.timeout = True
    with pytest.raises(TimeoutError):
        reconcile(ledger, transport, settings())
    assert counts(ledger.db) == {"pending": 1}
    reconcile(ledger, transport, settings())
    assert transport.posts == 1
    assert counts(ledger.db) == {"complete": 1}


def test_absent_ambiguous_relation_is_not_replayed(ledger):
    transport = Transport()
    transport.timeout = True
    transport.save_before_timeout = False
    with pytest.raises(TimeoutError):
        reconcile(ledger, transport, settings())
    with pytest.raises(RelationError, match="replay blocked"):
        reconcile(ledger, transport, settings())
    assert transport.posts == 1


def test_existing_other_relation_blocks_creation(ledger):
    transport = Transport()
    transport.kind = "relates_to"
    with pytest.raises(RelationError, match="different destination relation"):
        reconcile(ledger, transport, settings())
    assert transport.posts == 0


def test_removed_migrated_relation_cannot_be_silently_retained(ledger):
    transport = Transport()
    reconcile(ledger, transport, settings())
    with ledger.db:
        plan(ledger.db, SOURCE, [], "owner/repo")
    with pytest.raises(RelationError, match="cannot delete"):
        reconcile(ledger, transport, settings())
    assert counts(ledger.db) == {"removed": 1}


def test_missing_dependency_target_blocks_writes(ledger):
    with ledger.db:
        ledger.db.execute("DELETE FROM objects WHERE source_key=?", (TARGET,))
    transport = Transport()
    with pytest.raises(RelationError, match="explicit subset"):
        reconcile(ledger, transport, settings())
    assert transport.posts == 0


def test_cross_repository_dependency_is_not_mapped_to_same_number(ledger):
    with ledger.db:
        plan(ledger.db, SOURCE, [{"id": 20, "repository_url": "https://api.github.com/repos/other/repo"}], "owner/repo")
    assert ledger.db.execute("SELECT target_key FROM relations WHERE status='planned'").fetchone()[0] == "github:other/repo:issue:20"
    with pytest.raises(RelationError, match="explicit subset"):
        reconcile(ledger, Transport(), settings())


def test_unwritten_removed_dependency_is_omitted(ledger):
    with ledger.db:
        plan(ledger.db, SOURCE, [], "owner/repo")
    transport = Transport()
    reconcile(ledger, transport, settings())
    assert counts(ledger.db) == {"omitted": 1}
    assert transport.posts == 0
