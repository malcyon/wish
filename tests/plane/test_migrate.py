"""Exercise private migration history, original trust and interrupted writes."""
import json
import os
import sqlite3
import subprocess

import pytest

from tools.plane.migrate import (
    Ledger,
    MigrationError,
    export_source,
    github_pages,
    prepare,
    private_directory,
)


def snapshot():
    return {"version": 1, "repository": "owner/repo", "records": [{
        "issue": {"id": 55, "number": 3, "title": "Outside title", "body": "Original evidence",
                  "user": {"id": 99, "login": "Trusted display name"}, "state": "open",
                  "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
                  "labels": [{"name": "Priority: High"}, {"name": "question"}]},
        "comments": [{"id": 66, "body": "https://github.com/user-attachments/assets/example",
                      "user": {"id": 42}, "created_at": "2026-01-03T00:00:00Z"}],
        "timeline": [{"event": "cross-referenced", "source": {"issue": {"number": 4}}}],
    }]}


@pytest.fixture
def ledger(tmp_path):
    result = Ledger(tmp_path / "private", "disposable-project")
    yield result
    result.close()


def plan(ledger, source=None, trusted=frozenset({"42"})):
    return prepare(source or snapshot(), ledger, trusted, {3}, {"open": "state-open"}, {"question": "question-id", "human": "human-id"})


def test_rehearsal_keeps_authorship_and_records_gaps(ledger):
    summary = plan(ledger)
    assert summary == {"objects": {"planned": 2}, "outcomes": {"attachment:not_copied": 1, "label:mapped": 2, "timeline:not_reconciled": 1}}
    calls = []

    def create(kind, payload, parent):
        calls.append((kind, payload, parent))
        return {"id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002"}

    ledger.import_pending(create)
    assert calls[0][1]["priority"] == "high"
    assert calls[1][2] == "00000000-0000-0000-0000-000000000001"
    assert ledger.provenance("00000000-0000-0000-0000-000000000001")["trusted"] == 0
    assert ledger.provenance("00000000-0000-0000-0000-000000000002")["trusted"] == 1
    assert ledger.provenance("00000000-0000-0000-0000-000000000001")["source_author_id"] == "99"
    original = json.loads(ledger.db.execute("SELECT source FROM objects WHERE kind='issue'").fetchone()[0])
    assert original["created_at"] == "2026-01-01T00:00:00Z"
    assert original["user"]["login"] == "Trusted display name"
    plan(ledger)
    ledger.import_pending(create)
    assert len(calls) == 2


def test_timeout_survives_restart_and_blocks_duplicate(ledger, tmp_path):
    plan(ledger)

    def uncertain(*args):
        raise TimeoutError("Outside secret source text")

    with pytest.raises(MigrationError, match="unconfirmed"):
        ledger.import_pending(uncertain)
    reopened = Ledger(tmp_path / "private", "disposable-project")
    try:
        with pytest.raises(MigrationError, match="retry blocked"):
            reopened.import_pending(lambda *args: pytest.fail("Duplicate write"))
        assert reopened.summary()["objects"] == {"pending": 1, "planned": 1}
    finally:
        reopened.close()


@pytest.mark.parametrize("mutation", ["body", "trust", "priority"])
def test_changed_snapshot_or_trust_requires_reconciliation(ledger, mutation):
    plan(ledger)
    source = snapshot()
    trusted = frozenset({"42"})
    if mutation == "body":
        source["records"][0]["issue"]["body"] = "Changed"
    elif mutation == "trust":
        trusted = frozenset({"42", "99"})
    else:
        source["records"][0]["issue"]["labels"][0]["name"] = "Priority: Low"
    with pytest.raises(MigrationError, match="reconcile"):
        plan(ledger, source, trusted)


def test_scope_cannot_be_reused_for_another_project(tmp_path):
    Ledger(tmp_path / "private", "first").close()
    with pytest.raises(MigrationError, match="different"):
        Ledger(tmp_path / "private", "second")


def test_export_has_all_comments_and_events_without_printing(tmp_path, capsys):
    source = snapshot()["records"][0]
    endpoints = []

    def fetch(endpoint):
        endpoints.append(endpoint)
        if "/comments?" in endpoint:
            return source["comments"]
        if "/timeline?" in endpoint:
            return source["timeline"]
        return [source["issue"], {"pull_request": {}, "number": 9}]

    path = export_source(tmp_path / "private", "owner/repo", fetch)
    assert len(endpoints) == 3
    assert json.loads(path.read_text())["records"] == [source]
    assert path.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ("", "")


def test_export_pagination_and_errors_are_opaque(monkeypatch):
    def run(command, **kwargs):
        assert "--paginate" in command and "--slurp" in command
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, '[[{"id": 1}], [{"id": 2}]]')

    monkeypatch.setattr(subprocess, "run", run)
    assert github_pages("repos/owner/repo/issues") == [{"id": 1}, {"id": 2}]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "gh", stderr="Untrusted instructions")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(MigrationError) as failure:
        github_pages("repos/owner/repo/issues")
    assert "Untrusted" not in str(failure.value)


def test_private_directory_and_ledger_permissions(tmp_path):
    exposed = tmp_path / "exposed"
    exposed.mkdir(mode=0o755)
    with pytest.raises(MigrationError, match="0700"):
        private_directory(exposed)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.touch(mode=0o600)
    (private / "migration.sqlite3").symlink_to(target)
    with pytest.raises(OSError):
        Ledger(private, "project")
    assert target.read_bytes() == b""


@pytest.mark.parametrize("fault", ["unmapped", "priority", "missing"])
def test_invalid_subset_is_transactional(ledger, fault):
    source = snapshot()
    if fault == "unmapped":
        source["records"][0]["issue"]["labels"].append({"name": "unknown-label"})
    elif fault == "priority":
        source["records"][0]["issue"]["labels"] = []
    else:
        source["records"][0]["issue"]["number"] = 4
    with pytest.raises(MigrationError):
        plan(ledger, source)
    assert ledger.summary()["objects"] == {}


def test_duplicate_destination_is_ambiguous(ledger):
    plan(ledger)
    with pytest.raises(MigrationError, match="unconfirmed"):
        ledger.import_pending(lambda *args: {"id": "00000000-0000-0000-0000-000000000001"})
    assert ledger.summary()["objects"] == {"complete": 1, "pending": 1}
    assert ledger.provenance("unknown") is None


def test_ledger_keeps_sources_outside_checkout(ledger, tmp_path):
    plan(ledger)
    path = tmp_path / "private" / "migration.sqlite3"
    assert os.stat(path).st_mode & 0o777 == 0o600
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT count(*) FROM objects").fetchone()[0] == 2
    finally:
        connection.close()


def test_provenance_only_contains_confirmed_ids_and_exact_text(ledger, tmp_path):
    import hashlib

    plan(ledger)
    assert json.loads(ledger.write_provenance().read_text()) == {}
    ledger.import_pending(lambda kind, *args: {
        "id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002",
    })
    entries = json.loads((tmp_path / "private" / "provenance.json").read_text())
    entry = entries["00000000-0000-0000-0000-000000000001"]
    assert entry["original_account_id"] == "github:99"
    fields = {"name": "Outside title", "description_html": "<pre>Original evidence</pre>", "comment_html": None}
    assert entry["text_sha256"] == hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def test_rehearsal_requires_importer_and_checks_readback():
    from types import SimpleNamespace

    from tools.plane.migrate import rehearsal_writer

    project = "00000000-0000-0000-0000-000000000001"
    importer = "00000000-0000-0000-0000-000000000002"
    settings = SimpleNamespace(project=project, writes_enabled=True, importers={importer},
                               workspace="wish", resource="work-items", base_url="https://example.test")

    class Transport:
        def __init__(self):
            self.calls = []
            self.body = None
            self.author = importer
            self.changed = False

        def request(self, method, path, data=None):
            self.calls.append((method, path))
            if path == "users/me":
                return {"id": self.author}
            if method == "POST":
                self.body = data
                return {"id": project}
            return {**self.body, "id": project, "created_by": self.author,
                    **({"name": "Changed"} if self.changed else {})}

    transport = Transport()
    create = rehearsal_writer(project, settings, transport)
    result = create("issue", {"name": "Preserved"}, None)
    assert result["_migration_url"].startswith("https://example.test/wish/projects/")
    transport.changed = True
    with pytest.raises(MigrationError, match="content"):
        create("issue", {"name": "Preserved"}, None)
    transport.author = project
    with pytest.raises(MigrationError, match="importer"):
        rehearsal_writer(project, settings, transport)
    assert transport.calls[-1] == ("GET", "users/me")


def test_cli_dry_run_prints_counts_only(tmp_path, capsys):
    from tools.plane.migrate import main

    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot()))
    source.chmod(0o600)
    mapping = tmp_path / "labels.json"
    mapping.write_text(json.dumps({"question": "00000000-0000-0000-0000-000000000003", "human": "00000000-0000-0000-0000-000000000004"}))
    args = ["rehearse", "--label-map-file", str(mapping), "--snapshot", str(source), "--directory", str(tmp_path / "private"),
            "--rehearsal-project", "00000000-0000-0000-0000-000000000001", "--issue", "3",
            "--state-open", "00000000-0000-0000-0000-000000000002"]
    assert main(args) == 0
    output = capsys.readouterr()
    assert "planned" in output.out
    assert "Outside" not in output.out and not output.err
    assert main(args + ["--allow-writes"]) == 1
    output = capsys.readouterr()
    assert "source output withheld" in output.err
    assert "Outside" not in output.err


def test_public_origin_is_preserved_without_source_label(ledger):
    plan(ledger)
    ledger.import_pending(lambda kind, *args: {
        "id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002",
    })
    entries = json.loads(ledger.write_provenance().read_text())
    assert all(entry["human_thread"] is True for entry in entries.values())
    issue_payload = json.loads(ledger.db.execute("SELECT payload FROM objects WHERE kind='issue'").fetchone()[0])
    assert "human-id" in issue_payload["labels"]


def test_delta_preserves_old_source_and_updates_existing_destination(ledger):
    plan(ledger)
    def create(kind, *args):
        return {"id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002"}
    ledger.import_pending(create)
    source = snapshot()
    source["records"][0]["issue"]["body"] = "Corrected evidence"
    source["records"][0]["issue"]["updated_at"] = "2026-01-04T00:00:00Z"
    prepare(source, ledger, frozenset({"42"}), {3}, {"open": "state-open"},
            {"human": "human-id", "question": "question-id"}, reconcile=True)
    assert ledger.summary()["objects"] == {"complete": 1, "planned_update": 1}
    assert "00000000-0000-0000-0000-000000000001" not in json.loads(ledger.write_provenance().read_text())
    revisions = ledger.db.execute("SELECT source FROM revisions").fetchall()
    assert len(revisions) == 1
    assert json.loads(revisions[0][0])["body"] == "Original evidence"
    updates = []

    def update(kind, payload, parent, destination, previous):
        updates.append((payload, previous))
        assert destination == "00000000-0000-0000-0000-000000000001"
        return {"id": destination}

    ledger.import_pending(lambda *args: pytest.fail("Existing item was duplicated"), update)
    assert updates[0][0]["description_html"] == "<pre>Corrected evidence</pre>"
    assert updates[0][1]["description_html"] == "<pre>Original evidence</pre>"
    assert ledger.summary()["objects"] == {"complete": 2}


def test_delta_accepts_appended_comments_but_blocks_deleted_history(ledger):
    plan(ledger)
    source = snapshot()
    source["records"][0]["comments"].append({"id": 67, "body": "New evidence", "user": {"id": 42}})
    prepare(source, ledger, frozenset({"42"}), {3}, {"open": "state-open"},
            {"human": "human-id", "question": "question-id"}, reconcile=True)
    assert ledger.summary()["objects"] == {"planned": 3}
    with pytest.raises(MigrationError, match="deleted"):
        plan(ledger)
