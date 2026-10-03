"""Exercise opaque streaming, credential scope, attachment restart and readback."""
import hashlib
import os
import sqlite3
from types import SimpleNamespace

import pytest

from tools.plane.attachments import (
    AttachmentError,
    Transfer,
    counts,
    discover,
    initialize,
    plan,
    transfer_all,
)

requires_posix_storage = pytest.mark.skipif(
    os.name != "posix", reason="Completed downloads require POSIX ownership and directory fsync",
)

PROJECT = "00000000-0000-0000-0000-000000000001"
ISSUE = "00000000-0000-0000-0000-000000000002"
ASSET = "00000000-0000-0000-0000-000000000003"
IMPORTER = "00000000-0000-0000-0000-000000000004"
SOURCE = "github:owner/repo:issue:10"
URL = "https://github.com/user-attachments/assets/example"
DATA = b"Synthetic attachment bytes"


def settings(base_url="https://plane.example"):
    return SimpleNamespace(project=PROJECT, workspace="wish", resource="work-items", base_url=base_url,
                           writes_enabled=True, importers={IMPORTER}, token=lambda: "plane-secret")


class Response:
    def __init__(self, status=200, headers=None, body=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self.body = body
        self.chunks = chunks
        self.closed = False

    def json(self):
        return self.body

    def iter_content(self, size):
        assert size == 64 * 1024
        yield from self.chunks

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["verify"] is not False
        assert kwargs["stream"] is True
        if method == "POST" and "data" in kwargs:
            body = kwargs["data"]
            assert not isinstance(body, bytes)
            assert len(b"".join(body)) == len(body)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@requires_posix_storage
def test_authenticated_source_redirect_drops_credentials_and_keeps_bytes_opaque(tmp_path, capsys):
    token = tmp_path / "github-token"
    token.write_text("github-secret")
    token.chmod(0o600)
    session = Session(Response(302, {"Location": "https://objects.githubusercontent.com/file.bin"}),
                      Response(headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(DATA))}, chunks=[DATA[:4], DATA[4:]]))
    transfer = Transfer(settings(), {"github_attachment_token_file": str(token)}, session)
    result = transfer.download_source(URL, tmp_path)
    assert session.calls[0][2]["headers"] == {"Authorization": "Bearer github-secret", "Accept-Encoding": "identity"}
    assert session.calls[1][2]["headers"] == {"Accept-Encoding": "identity"}
    assert result["sha256"] == hashlib.sha256(DATA).hexdigest()
    assert (tmp_path / result["sha256"]).read_bytes() == DATA
    assert (tmp_path / result["sha256"]).stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ("", "")


def test_source_redirect_to_localhost_is_never_requested(tmp_path):
    session = Session(Response(302, {"Location": "https://localhost/secret"}))
    transfer = Transfer(settings(), {}, session)
    with pytest.raises(AttachmentError, match="approved hosts"):
        transfer.download_source(URL, tmp_path)
    assert len(session.calls) == 1


def test_size_limit_removes_partial_file(tmp_path):
    response = Response(chunks=[b"123", b"456"])
    transfer = Transfer(settings(), {"attachment_max_bytes": 5}, Session(response))
    with pytest.raises(AttachmentError, match="limit"):
        transfer.download_source(URL, tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_login_page_is_not_treated_as_an_attachment(tmp_path):
    response = Response(headers={"Content-Type": "text/html"}, chunks=[b"Login"])
    with pytest.raises(AttachmentError, match="web page"):
        Transfer(settings(), {}, Session(response)).download_source(URL, tmp_path)


def test_explicit_http_storage_has_no_api_token_and_streams_multipart(tmp_path):
    file = tmp_path / "file.bin"
    file.write_bytes(DATA)
    session = Session(Response(204))
    transfer = Transfer(settings("http://plane.internal"), {"allow_insecure_http": True}, session)
    transfer.upload({"url": "http://plane.internal/uploads", "fields": {"key": "opaque-key"}}, {
        "local_path": str(file), "filename": "file.bin", "content_type": "application/octet-stream",
        "size": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest(),
    })
    assert "X-API-Key" not in session.calls[0][2]["headers"]
    assert "Authorization" not in session.calls[0][2]["headers"]
    with pytest.raises(AttachmentError, match="explicit HTTP"):
        Transfer(settings("http://plane.internal"), {}, Session())


def test_unapproved_storage_origin_is_blocked_before_upload(tmp_path):
    transfer = Transfer(settings(), {}, Session())
    with pytest.raises(AttachmentError, match="not approved"):
        transfer.upload({"url": "https://other.example/upload", "fields": {}}, {})


@requires_posix_storage
def test_confirmation_accepts_empty_204_and_download_verifies_remote_bytes(tmp_path):
    path = f"workspaces/wish/projects/{PROJECT}/work-items/{ISSUE}/attachments"
    metadata = {"size": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest()}
    record = {"id": ASSET, "issue": ISSUE, "project": PROJECT, "created_by": IMPORTER,
              "is_uploaded": True, "external_source": "github", "external_id": "external",
              "size": len(DATA)}
    session = Session(Response(204), Response(body=[record]),
                      Response(302, {"Location": "https://plane.example/uploads/signed"}),
                      Response(chunks=[DATA]))
    transfer = Transfer(settings(), {}, session)
    transfer.confirm(f"{path}/{ASSET}")
    transfer.verify_asset(path, ASSET, metadata, tmp_path, "external")
    assert session.calls[-1][2]["headers"] == {"Accept-Encoding": "identity"}
    assert session.calls[0][2]["headers"] == {"X-API-Key": "plane-secret"}


def test_remote_attachment_hash_mismatch_fails(tmp_path):
    transfer = Transfer(settings(), {}, Session(Response(chunks=[b"Different bytes"])))
    with pytest.raises(AttachmentError, match="differ"):
        transfer._download("https://plane.example/uploads/signed", tmp_path,
                           expected_size=len(DATA), expected_hash=hashlib.sha256(DATA).hexdigest())
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def ledger(tmp_path):
    # Transfer-state tests use portable SQLite; private-file enforcement is tested separately.
    ledger = SimpleNamespace(db=sqlite3.connect(tmp_path / "ledger.sqlite3"), project_id=PROJECT)
    ledger.db.execute("CREATE TABLE objects (source_key TEXT PRIMARY KEY, kind TEXT, status TEXT, plane_id TEXT)")
    initialize(ledger.db)
    with ledger.db:
        ledger.db.execute("INSERT INTO objects VALUES (?, 'issue', 'complete', ?)", (SOURCE, ISSUE))
        plan(ledger.db, SOURCE, {URL})
    yield ledger
    ledger.db.close()


class FakeTransfer:
    def __init__(self):
        self.settings = settings()
        self.allocated = 0
        self.uploaded = 0
        self.confirmed = 0
        self.verified = 0
        self.fail = None

    def check_identity(self):
        pass

    def download_source(self, url, directory):
        assert url == URL
        return {"size": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest(), "filename": "test.bin",
                "content_type": "application/octet-stream", "local_path": str(directory / "test.bin")}

    def allocate(self, path, metadata, external_id):
        self.allocated += 1
        if self.fail == "allocation":
            raise TimeoutError
        return {"asset_id": ASSET, "upload_data": {"url": "https://plane.example/uploads", "fields": {}},
                "attachment": {"id": ASSET, "issue": ISSUE, "project": PROJECT, "size": len(DATA),
                               "created_by": IMPORTER, "external_id": external_id, "external_source": "github"}}

    def validate_upload(self, credentials, metadata):
        pass

    def upload(self, credentials, metadata):
        self.uploaded += 1
        if self.fail == "upload":
            raise TimeoutError

    def confirm(self, path):
        self.confirmed += 1
        if self.fail == "confirmation":
            raise TimeoutError

    def verify_asset(self, *args):
        self.verified += 1
        if self.fail == "verification":
            raise AttachmentError("Remote bytes differ")


def test_all_attachment_stages_survive_rerun_without_new_upload(ledger):
    transfer = FakeTransfer()
    transfer_all(ledger, transfer)
    transfer_all(ledger, transfer)
    assert counts(ledger.db) == {"verified": 1}
    assert (transfer.allocated, transfer.uploaded, transfer.confirmed, transfer.verified) == (1, 1, 1, 2)
    assert ledger.db.execute("SELECT upload_data FROM attachments").fetchone()[0] is None


@pytest.mark.parametrize("stage", ["allocation", "upload"])
def test_ambiguous_allocation_or_upload_never_replays(ledger, stage):
    transfer = FakeTransfer()
    transfer.fail = stage
    with pytest.raises(TimeoutError):
        transfer_all(ledger, transfer)
    with pytest.raises(AttachmentError, match="replay blocked"):
        transfer_all(ledger, transfer)
    assert transfer.allocated == 1
    assert transfer.uploaded == (1 if stage == "upload" else 0)


def test_lost_confirmation_can_recover_by_readback_without_repeating_patch(ledger):
    transfer = FakeTransfer()
    transfer.fail = "confirmation"
    with pytest.raises(TimeoutError):
        transfer_all(ledger, transfer)
    assert counts(ledger.db) == {"confirmation_pending": 1}
    transfer.fail = None
    transfer_all(ledger, transfer)
    assert counts(ledger.db) == {"verified": 1}
    assert transfer.confirmed == 1


def test_failed_verification_stays_incomplete_until_bytes_match(ledger):
    transfer = FakeTransfer()
    transfer.fail = "verification"
    with pytest.raises(AttachmentError, match="differ"):
        transfer_all(ledger, transfer)
    assert counts(ledger.db) == {"confirmed": 1}
    transfer.fail = None
    transfer_all(ledger, transfer)
    assert counts(ledger.db) == {"verified": 1}
    assert transfer.uploaded == 1


def test_removed_uploaded_attachment_blocks_delta_acceptance(ledger):
    transfer_all(ledger, FakeTransfer())
    with ledger.db:
        plan(ledger.db, SOURCE, set())
    with pytest.raises(AttachmentError, match="removed"):
        transfer_all(ledger, FakeTransfer())


def test_discovery_includes_legacy_and_current_urls_without_external_fetches():
    text = f'![Image]({URL}) <img src="https://user-images.githubusercontent.com/1/file.png"> https://github.com/owner/repo/files/1/data.zip https://other.example/private'
    assert discover(text) == {URL, "https://user-images.githubusercontent.com/1/file.png", "https://github.com/owner/repo/files/1/data.zip"}
