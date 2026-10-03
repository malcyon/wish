"""Exercise private migration history, original trust and interrupted writes."""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from tools.plane.migrate import (
    Ledger,
    MigrationError,
    export_source,
    github_pages,
    prepare,
    private_directory,
)

_PRIVATE_STORAGE_TESTS = {
    "test_scope_cannot_be_reused_for_another_project",
    "test_export_has_all_comments_and_events_without_printing",
    "test_private_directory_and_ledger_permissions",
    "test_cli_dry_run_prints_counts_only",
    "test_production_writer_requires_separate_explicit_configuration",
    "test_production_dry_run_does_not_write_without_allow_import",
}


@pytest.fixture(autouse=True)
def require_private_storage_permissions(request):
    """Migration storage enforces POSIX ownership and private file modes."""
    if os.name == "posix":
        return
    if "ledger" in request.fixturenames or request.node.originalname in _PRIVATE_STORAGE_TESTS:
        pytest.skip("Migration storage requires POSIX ownership and private file modes")

def snapshot():
    return {"version": 2, "repository": "owner/repo", "records": [{
        "issue": {"id": 55, "number": 3, "title": "Outside title", "body": "Original evidence",
                  "user": {"id": 99, "login": "Trusted display name"}, "state": "open",
                  "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
                  "labels": [{"name": "Priority: High"}, {"name": "question"}]},
        "comments": [{"id": 66, "body": "https://github.com/user-attachments/assets/example",
                      "user": {"id": 42}, "created_at": "2026-01-03T00:00:00Z"}],
        "timeline": [{"event": "cross-referenced", "source": {"issue": {"number": 4}}}],
        "blocked_by": [],
    }]}


@pytest.fixture
def ledger(tmp_path):
    result = Ledger(tmp_path / "private", "disposable-project")
    yield result
    result.close()


def plan(ledger, source=None, trusted=frozenset({"42"})):
    return prepare(source or snapshot(), ledger, trusted, {3}, {"open": "state-open"}, {"question": "question-id", "Priority: High": "high-id", "Priority: Low": "low-id"})


def test_rehearsal_keeps_authorship_and_records_gaps(ledger):
    summary = plan(ledger)
    assert summary == {"objects": {"planned": 2}, "attachments": {"planned": 1}, "relations": {}, "outcomes": {"dependencies:preserved": 1, "label:mapped": 2, "timeline:preserved": 1}}
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
        if "/dependencies/blocked_by?" in endpoint:
            return source["blocked_by"]
        return [source["issue"], {"pull_request": {}, "number": 9}]

    path = export_source(tmp_path / "private", "owner/repo", fetch)
    assert len(endpoints) == 4
    assert json.loads(path.read_text())["records"] == [source]
    assert path.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ("", "")


def test_export_pagination_and_errors_are_opaque(monkeypatch):
    def run(command, **kwargs):
        assert "--paginate" in command and "--slurp" not in command
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, '[ {"id": 1}]\n[{"id": 2}]\n[]')

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
    ledger.import_pending(lambda kind, payload, *args: {
        **payload,
        "id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002",
    })
    entries = json.loads((tmp_path / "private" / "provenance.json").read_text())
    entry = entries["00000000-0000-0000-0000-000000000001"]
    assert entry["original_account_id"] == "github:99"
    fields = {"name": "Outside title", "description_html": "<div><p>Original evidence</p>\n</div>", "comment_html": None}
    assert entry["text_sha256"] == hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def test_rehearsal_requires_importer_and_checks_readback():
    from types import SimpleNamespace

    from tools.plane.migrate import migration_writer

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
    create = migration_writer(project, settings, transport)
    result = create("issue", {"name": "Preserved"}, None)
    assert result["_migration_url"].startswith("https://example.test/wish/projects/")
    transport.changed = True
    with pytest.raises(MigrationError, match="content"):
        create("issue", {"name": "Preserved"}, None)
    transport.author = project
    with pytest.raises(MigrationError, match="importer"):
        migration_writer(project, settings, transport)
    assert transport.calls[-1] == ("GET", "users/me")


def test_cli_dry_run_prints_counts_only(tmp_path, capsys):
    from tools.plane.migrate import main

    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot()))
    source.chmod(0o600)
    mapping = tmp_path / "labels.json"
    mapping.write_text(json.dumps({"question": "00000000-0000-0000-0000-000000000003", "Priority: High": "00000000-0000-0000-0000-000000000004"}))
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
    ledger.import_pending(lambda kind, payload, *args: {
        **payload,
        "id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002",
    })
    entries = json.loads(ledger.write_provenance().read_text())
    assert all(entry["human_thread"] is True for entry in entries.values())
    issue_payload = json.loads(ledger.db.execute("SELECT payload FROM objects WHERE kind='issue'").fetchone()[0])
    assert issue_payload["labels"] == ["high-id", "question-id"]


def test_delta_preserves_old_source_and_updates_existing_destination(ledger):
    plan(ledger)
    def create(kind, *args):
        return {"id": "00000000-0000-0000-0000-000000000001" if kind == "issue" else "00000000-0000-0000-0000-000000000002"}
    ledger.import_pending(create)
    source = snapshot()
    source["records"][0]["issue"]["body"] = "Corrected evidence"
    source["records"][0]["issue"]["updated_at"] = "2026-01-04T00:00:00Z"
    prepare(source, ledger, frozenset({"42"}), {3}, {"open": "state-open"},
            {"Priority: High": "high-id", "question": "question-id"}, reconcile=True)
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
    assert updates[0][0]["description_html"] == "<div><p>Corrected evidence</p>\n</div>"
    assert updates[0][1]["description_html"] == "<div><p>Original evidence</p>\n</div>"
    assert ledger.summary()["objects"] == {"complete": 2}


def test_delta_accepts_appended_comments_but_blocks_deleted_history(ledger):
    plan(ledger)
    source = snapshot()
    source["records"][0]["comments"].append({"id": 67, "body": "New evidence", "user": {"id": 42}})
    prepare(source, ledger, frozenset({"42"}), {3}, {"open": "state-open"},
            {"Priority: High": "high-id", "question": "question-id"}, reconcile=True)
    assert ledger.summary()["objects"] == {"planned": 3}
    with pytest.raises(MigrationError, match="deleted"):
        plan(ledger)


def test_service_state_lock_excludes_backup_and_keeps_the_same_file(tmp_path):
    import sys

    from tools.plane.migrate import operation_lock

    if sys.platform != "linux":
        pytest.skip("Service-side import locking requires Linux")
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    lock = directory / "state.lock"
    with operation_lock(lock):
        inode = lock.stat().st_ino
        with pytest.raises(MigrationError, match="holds"):
            with operation_lock(lock):
                pytest.fail("Concurrent backup/import entered the protected operation")
    assert lock.stat().st_ino == inode
    with operation_lock(lock):
        assert lock.stat().st_ino == inode


def test_service_state_lock_does_not_follow_a_symlink(tmp_path):
    import sys

    from tools.plane.migrate import operation_lock

    if sys.platform != "linux":
        pytest.skip("Service-side import locking requires Linux")
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = tmp_path / "unrelated"
    target.write_text("Preserve")
    lock = directory / "state.lock"
    lock.symlink_to(target)
    with pytest.raises(OSError):
        with operation_lock(lock):
            pytest.fail("Followed a lock symlink")
    assert target.read_text() == "Preserve"


def test_attachment_reference_keeps_original_comment_author_and_time(ledger):
    plan(ledger)
    origin, author, created = ledger.db.execute("SELECT origin_key,original_author_id,created_at FROM attachment_sources").fetchone()
    assert origin == "github:owner/repo:comment:66"
    assert author == "github:42"
    assert created == "2026-01-03T00:00:00Z"


def test_ledger_cannot_be_reused_on_another_service(ledger):
    from types import SimpleNamespace

    settings = SimpleNamespace(base_url="http://plane.internal", workspace="wish", project="disposable-project")
    ledger.bind_service(settings)
    ledger.bind_service(settings)
    settings.base_url = "http://other.internal"
    with pytest.raises(MigrationError, match="different Plane service"):
        ledger.bind_service(settings)


def test_import_excludes_origin_labels_but_keeps_priority_label_and_human_provenance(ledger):
    source = snapshot()
    source["records"][0]["issue"]["labels"].extend([{"name": "AI"}, {"name": "HuMaN"}])
    plan(ledger, source, trusted=frozenset({"42", "99"}))
    payload = json.loads(ledger.db.execute("SELECT payload FROM objects WHERE kind='issue'").fetchone()[0])
    assert payload["labels"] == ["high-id", "question-id"]
    assert payload["priority"] == "high"
    assert ledger.db.execute("SELECT human_thread FROM origins").fetchone()[0] == 1
    assert ledger.summary()["outcomes"]["label:excluded"] == 2
    original = json.loads(ledger.db.execute("SELECT source FROM objects WHERE kind='issue'").fetchone()[0])
    assert {label["name"] for label in original["labels"]} == {"Priority: High", "question", "AI", "HuMaN"}


def test_excluded_origin_labels_cannot_be_mapped_into_plane(ledger):
    with pytest.raises(MigrationError, match="must not be recreated"):
        prepare(snapshot(), ledger, frozenset({"42"}), {3}, {"open": "open"},
                {"question": "question-id", "Priority: High": "high-id", "human": "human-id"})
    assert ledger.summary()["objects"] == {}


def test_closed_not_planned_keeps_reason_while_mapping_to_completed(ledger):
    source = snapshot()
    issue = source["records"][0]["issue"]
    issue.update(state="closed", state_reason="not_planned")
    prepare(source, ledger, frozenset({"42"}), {3}, {"cancelled": "completed-state"},
            {"question": "question-id", "Priority: High": "high-id"})
    payload, preserved = ledger.db.execute("SELECT payload,source FROM objects WHERE kind='issue'").fetchone()
    assert json.loads(payload)["state"] == "completed-state"
    assert json.loads(preserved)["state_reason"] == "not_planned"


def test_missing_priority_requires_explicit_recorded_fallback(ledger):
    source = snapshot()
    source["records"][0]["issue"]["labels"] = [{"name": "question"}]
    prepare(source, ledger, frozenset({"42"}), {3}, {"open": "open"},
            {"question": "question-id"}, default_priority="medium")
    payload = json.loads(ledger.db.execute("SELECT payload FROM objects WHERE kind='issue'").fetchone()[0])
    assert payload["priority"] == "medium"
    assert payload["labels"] == ["question-id"]
    assert ledger.summary()["outcomes"]["priority:explicit_fallback"] == 1


def test_open_scope_adds_closed_dependency_chain_before_unrelated_history():
    import copy

    from tools.plane.migrate import select_issues

    source = snapshot()
    first = source["records"][0]
    dependency = copy.deepcopy(first)
    dependency["issue"].update(id=56, number=4, state="closed")
    history = copy.deepcopy(first)
    history["issue"].update(id=57, number=5, state="closed")
    first["blocked_by"] = [{"id": 56}]
    source["records"].extend([dependency, history])
    assert select_issues(source, "open", []) == {3, 4}
    assert select_issues(source, "history", []) == {4, 5}
    assert select_issues(source, "all", []) == {3, 4, 5}
    assert select_issues(source, "selected", [3]) == {3, 4}


def test_production_writer_requires_separate_explicit_configuration(tmp_path, monkeypatch):
    from tools.plane.migrate import migration_writer

    project = "00000000-0000-0000-0000-000000000001"
    agent = "00000000-0000-0000-0000-000000000002"
    importer = "00000000-0000-0000-0000-000000000003"
    config = {"base_url": "http://plane.internal", "allow_insecure_http": True,
              "workspace_slug": "wish", "project_id": project, "import_project_id": project,
              "agent_account_id": agent, "trusted_account_ids": [agent], "importer_account_ids": [importer],
              "token_file": str(tmp_path / "token"), "journal_file": str(tmp_path / "journal"), "writes_enabled": True}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    monkeypatch.setenv("WISH_PLANE_CONFIG", str(path))
    with pytest.raises(MigrationError, match="import_enabled"):
        migration_writer(project, production=True)
    with pytest.raises(MigrationError, match="project mode"):
        migration_writer(project)
    config.update(import_enabled=True, rehearsal_project_id=project)
    path.write_text(json.dumps(config))
    with pytest.raises(MigrationError, match="must be distinct"):
        migration_writer(project, production=True)


def test_production_dry_run_does_not_write_without_allow_import(tmp_path, monkeypatch, capsys):
    import tools.plane.migrate as migrate

    project = "00000000-0000-0000-0000-000000000001"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(snapshot()))
    source.chmod(0o600)
    states = tmp_path / "states.json"
    states.write_text(json.dumps({name: f"00000000-0000-0000-0000-00000000000{index}" for index, name in enumerate(migrate.STATE_GROUPS, 2)}))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"Priority: High": "00000000-0000-0000-0000-000000000006", "question": "00000000-0000-0000-0000-000000000007"}))
    monkeypatch.setattr(migrate, "migration_writer", lambda *args, **kwargs: pytest.fail("Dry run attempted a live writer"))
    args = ["import", "--directory", str(tmp_path / "private"), "--snapshot", str(source), "--project", project,
            "--scope", "open", "--state-map-file", str(states), "--label-map-file", str(labels)]
    assert migrate.main(args) == 0
    output = capsys.readouterr()
    assert "Migration counts" in output.out and "Outside" not in output.out
    ledger = Ledger(tmp_path / "private", project)
    try:
        payload = json.loads(ledger.db.execute("SELECT payload FROM objects WHERE kind='issue'").fetchone()[0])
        assert payload["state"] == "00000000-0000-0000-0000-000000000002"
    finally:
        ledger.close()


def test_issue_import_order_keeps_open_work_before_closed_history(ledger):
    with ledger.db:
        ledger.record("closed", "issue", {"state": "closed", "created_at": "2000-01-01"}, {}, frozenset())
        ledger.record("open", "issue", {"state": "open", "created_at": "2026-01-01"}, {}, frozenset())
    seen = []

    def create(kind, payload, parent):
        current = ledger.db.execute("SELECT source_key FROM objects WHERE status='pending'").fetchone()[0]
        seen.append(current)
        return {"id": f"00000000-0000-0000-0000-{len(seen):012d}"}

    ledger.import_pending(create)
    assert seen == ["open", "closed"]


def test_live_state_mapping_checks_names_and_workflow_groups_before_writes():
    from types import SimpleNamespace

    from tools.plane.migrate import STATE_GROUPS, migration_writer

    project = "00000000-0000-0000-0000-000000000001"
    importer = "00000000-0000-0000-0000-000000000002"
    settings = SimpleNamespace(project=project, workspace="wish", resource="work-items", writes_enabled=True,
                               importers={importer}, base_url="http://plane.internal")
    definitions = {name: f"00000000-0000-0000-0000-00000000000{index}" for index, name in enumerate(STATE_GROUPS, 3)}

    class Transport:
        def request(self, method, path, data=None, params=None):
            assert method == "GET"
            if path == "users/me":
                return {"id": importer}
            return {"results": [{"id": identifier, "name": name, "group": "unstarted" if name == "Backlog" else STATE_GROUPS[name]}
                                for name, identifier in definitions.items()], "next_page_results": False}

    with pytest.raises(MigrationError, match="workflow groups"):
        migration_writer(project, settings, Transport(), production=True, state_definitions=definitions)


@pytest.mark.skipif(sys.platform != "linux", reason="Service-side import locking requires Linux")
@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_interrupted_migration_blocks_backup_until_success(tmp_path, exception):
    from tools.plane.migrate import migration_marker, operation_lock

    directory = private_directory(tmp_path / "private")
    marker = directory / ".migration-in-progress"
    with operation_lock(directory / "state.lock"):
        with pytest.raises(exception):
            with migration_marker(directory, True):
                assert marker.stat().st_mode & 0o777 == 0o600
                raise exception("Interrupted")
    assert marker.exists()
    with operation_lock(directory / "state.lock"), migration_marker(directory, False):
        pass
    assert marker.exists(), "A dry run must not certify an interrupted import"
    with operation_lock(directory / "state.lock"), migration_marker(directory, True):
        assert marker.exists()
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="Migration markers require POSIX file permissions")
def test_migration_marker_rejects_symlink(tmp_path):
    from tools.plane.migrate import migration_marker

    directory = private_directory(tmp_path / "private")
    target = tmp_path / "target"
    target.write_text("Keep")
    (directory / ".migration-in-progress").symlink_to(target)
    with pytest.raises(OSError):
        with migration_marker(directory, True):
            pytest.fail("Symlink marker accepted")
    assert target.read_text() == "Keep"


def test_normalized_import_keeps_exact_remote_provenance_and_original_source(ledger):
    import hashlib
    from types import SimpleNamespace

    from tools.plane.migrate import migration_writer

    source = snapshot()
    body = 'A "quoted" value and an apostrophe\'s value'
    source["records"][0]["issue"]["body"] = body
    source["records"][0]["comments"][0]["body"] = body
    plan(ledger, source)
    project = "00000000-0000-0000-0000-000000000010"
    importer = "00000000-0000-0000-0000-000000000011"
    settings = SimpleNamespace(project=project, writes_enabled=True, importers={importer},
                               workspace="wish", resource="work-items", base_url="https://example.test")

    class NormalizingTransport:
        def __init__(self):
            self.records = {}

        def request(self, method, path, data=None):
            if path == "users/me":
                return {"id": importer}
            if method == "POST":
                identifier = f"00000000-0000-0000-0000-{len(self.records) + 1:012d}"
                record = {**data, "id": identifier, "created_by": importer, "project": project}
                for field in ("description_html", "comment_html"):
                    if field in record:
                        record[field] = record[field].replace("&quot;", '"').replace("&#x27;", "'")
                self.records[identifier] = record
                return record
            return self.records[path.rsplit("/", 1)[-1]]

    transport = NormalizingTransport()
    ledger.import_pending(migration_writer(project, settings, transport))
    entries = json.loads(ledger.write_provenance().read_text())
    assert len(entries) == 2
    for identifier, record in transport.records.items():
        fields = {key: record.get(key) for key in ("name", "description_html", "comment_html")}
        assert entries[identifier]["text_sha256"] == hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    original = json.loads(ledger.db.execute("SELECT source FROM objects WHERE kind='issue'").fetchone()[0])
    assert original["body"] == body
    assert ledger.summary()["objects"] == {"complete": 2}


@pytest.mark.parametrize("changed", ['<pre>Changed</pre>', '<p>A "quoted" value</p>', '<pre class="added">A "quoted" value</pre>'])
def test_normalized_import_rejects_changed_text_or_markup(changed):
    from types import SimpleNamespace

    from tools.plane.migrate import migration_writer

    project = "00000000-0000-0000-0000-000000000010"
    importer = "00000000-0000-0000-0000-000000000011"
    settings = SimpleNamespace(project=project, writes_enabled=True, importers={importer},
                               workspace="wish", resource="work-items", base_url="https://example.test")

    class ChangedTransport:
        def request(self, method, path, data=None):
            if path == "users/me":
                return {"id": importer}
            return {"id": project, "created_by": importer, "description_html": changed}

    writer = migration_writer(project, settings, ChangedTransport())
    with pytest.raises(MigrationError, match="content"):
        writer("issue", {"description_html": '<pre>A &quot;quoted&quot; value</pre>'}, None)


def test_markdown_descriptions_and_comments_preserve_source_and_rich_blocks(ledger):
    body = '# Heading\n\n- List item\n\n[Link](https://example.test)\n\n```python\nprint("Safe")\n```\n\n| One | Two |\n| --- | --- |\n| A | B |\n\n~~Removed~~'
    source = snapshot()
    source["records"][0]["issue"]["body"] = body
    source["records"][0]["comments"][0]["body"] = body
    plan(ledger, source)
    for kind, raw, payload in ledger.db.execute("SELECT kind,source,payload FROM objects"):
        assert json.loads(raw)["body"] == body
        rendered = json.loads(payload)["description_html" if kind == "issue" else "comment_html"]
        assert "<h1>Heading</h1>" in rendered
        assert "<li>List item</li>" in rendered
        assert '<a href="https://example.test" rel="noopener noreferrer">Link</a>' in rendered
        assert '<pre><code class="language-python">' in rendered
        assert "<table>" in rendered and "<th>One</th>" in rendered and "<td>A</td>" in rendered
        assert "<s>Removed</s>" in rendered
        assert rendered.startswith("<div>") and rendered.endswith("</div>")


def test_markdown_source_html_and_unsafe_links_are_not_executable():
    from tools.plane.migrate import render_markdown

    rendered = render_markdown('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n[Unsafe](javascript:alert(1))')
    assert "<script" not in rendered and "<img" not in rendered
    assert 'href="javascript:' not in rendered
    assert "&lt;script&gt;" in rendered and "&lt;img" in rendered
