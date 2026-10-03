"""Transfer opaque issue attachments with bounded streams and durable write stages."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from uuid import UUID, uuid4

from tools.plane.policy import PlaneError

SOURCE_HOSTS = frozenset({
    "github.com", "user-images.githubusercontent.com", "private-user-images.githubusercontent.com",
    "objects.githubusercontent.com", "github-production-user-asset-6210df.s3.amazonaws.com",
})
CHUNK_SIZE = 64 * 1024


class AttachmentError(PlaneError):
    """Report a transfer failure without exposing attachment bytes or signed URLs."""


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS attachments (
        source_key TEXT NOT NULL, source_url TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'planned', size INTEGER, sha256 TEXT,
        filename TEXT, content_type TEXT, local_path TEXT,
        asset_id TEXT, upload_data TEXT,
        PRIMARY KEY(source_key,source_url)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS attachment_sources (
        source_key TEXT NOT NULL, source_url TEXT NOT NULL, origin_key TEXT NOT NULL,
        original_author_id TEXT, created_at TEXT, source_digest TEXT NOT NULL,
        PRIMARY KEY(source_key,source_url,origin_key,source_digest)
    )""")


def note_sources(db, source_key, origin_key, source):
    """Keep each attachment reference tied to its original issue or comment revision."""
    original_id = (source.get("user") or {}).get("id")
    author = f"github:{original_id}" if type(original_id) is int else None
    checksum = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    for url in discover(source.get("body") or ""):
        db.execute("INSERT OR IGNORE INTO attachment_sources VALUES (?,?,?,?,?,?)",
                   (source_key, url, origin_key, author, source.get("created_at"), checksum))


def source_url(value):
    """Accept only GitHub attachment endpoints as original download locations."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.fragment:
        return False
    if parsed.hostname in {"user-images.githubusercontent.com", "private-user-images.githubusercontent.com"}:
        return True
    return parsed.hostname == "github.com" and bool(re.fullmatch(
        r"/(?:user-attachments/(?:assets|files)/[^\s]+|[^/]+/[^/]+/(?:assets|files)/[^\s]+)", parsed.path,
    ))


def discover(text):
    """Find hosted attachment references without interpreting their file contents."""
    candidates = re.findall(r'https://[^\s<>"\)\]]+', text)
    return {value.rstrip(".,;") for value in candidates if source_url(value.rstrip(".,;"))}


def plan(db, source_key, urls):
    previous = dict(db.execute("SELECT source_url,stage FROM attachments WHERE source_key=?", (source_key,)))
    for url in urls:
        if not source_url(url):
            raise AttachmentError("Unsupported original attachment URL")
        db.execute("INSERT INTO attachments (source_key,source_url) VALUES (?,?) ON CONFLICT(source_key,source_url) DO UPDATE SET stage=CASE WHEN attachments.stage='omitted' THEN 'planned' ELSE attachments.stage END", (source_key, url))
    for url, stage in previous.items():
        if url not in urls:
            db.execute("UPDATE attachments SET stage=? WHERE source_key=? AND source_url=?",
                       ("omitted" if stage in {"planned", "downloaded", "omitted"} else "removed", source_key, url))


def _origin(url):
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise AttachmentError("Invalid attachment URL origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _private_token(path):
    path = Path(path)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
        raise AttachmentError("Attachment credential file must have mode 0600")
    token = path.read_text().strip()
    if not token or "\n" in token or "\r" in token:
        raise AttachmentError("Invalid attachment credential file")
    return token


class Multipart:
    """Stream a known-length multipart body without loading its file into memory."""

    def __init__(self, fields, path, filename, content_type, maximum_seconds=300):
        self.maximum_seconds = maximum_seconds
        self.path = Path(path)
        self.boundary = uuid4().hex
        chunks = []
        for name, value in fields.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not isinstance(value, str):
                raise AttachmentError("Invalid presigned form field")
            chunks.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        if any(char in filename + content_type for char in '\r\n"'):
            raise AttachmentError("Invalid multipart file metadata")
        chunks.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
        self.prefix = b"".join(chunks)
        self.suffix = f"\r\n--{self.boundary}--\r\n".encode()

    def __len__(self):
        return len(self.prefix) + self.path.stat().st_size + len(self.suffix)

    def __iter__(self):
        started = time.monotonic()
        yield self.prefix
        with self.path.open("rb") as stream:
            while chunk := stream.read(CHUNK_SIZE):
                if time.monotonic() - started > self.maximum_seconds:
                    raise AttachmentError("Attachment upload exceeded its time limit")
                yield chunk
        yield self.suffix


class Transfer:
    """Keep source, Plane and storage credentials confined to their own requests."""

    def __init__(self, settings, config, session=None):
        self.settings = settings
        self.maximum_size = int(config.get("attachment_max_bytes", 25 * 1024 * 1024))
        self.maximum_seconds = int(config.get("attachment_max_seconds", 300))
        if not 1 <= self.maximum_size <= 1024 * 1024 * 1024 or not 1 <= self.maximum_seconds <= 3600:
            raise AttachmentError("Invalid attachment transfer limits")
        self.source_token_file = config.get("github_attachment_token_file")
        self.source_hosts = SOURCE_HOSTS | frozenset(config.get("github_attachment_redirect_hosts", []))
        self.storage_origins = {settings.base_url} | set(config.get("attachment_storage_origins", []))
        for origin in self.storage_origins:
            parsed = urlsplit(origin)
            if _origin(origin) != origin or parsed.path or parsed.query:
                raise AttachmentError("Storage allowlist entries must be exact origins")
            if parsed.scheme != "https" and not (parsed.scheme == "http" and config.get("allow_insecure_http") is True):
                raise AttachmentError("HTTP storage requires explicit HTTP authorization")
        if session is None:
            import requests
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.verify = os.environ.get("REQUESTS_CA_BUNDLE") or True

    def _request(self, method, url, **kwargs):
        try:
            if hasattr(self.session, "cookies"):
                self.session.cookies.clear()
            return self.session.request(method, url, timeout=(10, 30), allow_redirects=False,
                                        stream=True, verify=self.verify, **kwargs)
        except Exception as error:
            raise AttachmentError("Attachment request failed; write stage retained") from error

    def api(self, method, path, data=None, accepted=(200,)):
        prefix = f"workspaces/{self.settings.workspace}/projects/{self.settings.project}/work-items/"
        if (not path.startswith(prefix) and path != "users/me") or any(value in path for value in ("..", "?", "#", "%")):
            raise AttachmentError("Attachment API path is outside the configured project")
        response = self._request(method, f"{self.settings.base_url}/api/v1/{path.strip('/')}/",
                                 headers={"X-API-Key": self.settings.token()}, json=data)
        if response.status_code not in accepted:
            response.close()
            raise AttachmentError(f"Attachment API returned HTTP {response.status_code}")
        return response

    def _download(self, url, directory, *, source=False, expected_size=None, expected_hash=None):
        start = time.monotonic()
        response = None
        token = _private_token(self.source_token_file) if source and self.source_token_file else None
        for redirect in range(6):
            parsed = urlsplit(url)
            if source:
                if parsed.scheme != "https" or parsed.hostname not in self.source_hosts or parsed.username or parsed.password or parsed.port not in {None, 443}:
                    raise AttachmentError("Source attachment redirect is outside the approved hosts")
                if parsed.hostname == "github.com" and not source_url(url):
                    raise AttachmentError("Source attachment redirected to a non-attachment page")
            elif _origin(url) not in self.storage_origins:
                raise AttachmentError("Storage download origin is not approved")
            headers = {"Accept-Encoding": "identity"}
            if token and redirect == 0 and parsed.hostname == "github.com":
                headers["Authorization"] = f"Bearer {token}"
            response = self._request("GET", url, headers=headers)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise AttachmentError("Attachment redirect has no destination")
            url = urljoin(url, location)
        else:
            raise AttachmentError("Attachment redirect limit exceeded")
        temporary = None
        try:
            if response.status_code != 200:
                raise AttachmentError(f"Attachment download returned HTTP {response.status_code}")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise AttachmentError("Attachment server ignored the uncompressed transfer request")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) > self.maximum_size):
                raise AttachmentError("Attachment exceeds the configured byte limit")
            content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise AttachmentError("Attachment download returned a web page")
            descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".attachment-")
            size, checksum = 0, hashlib.sha256()
            with os.fdopen(descriptor, "wb") as stream:
                for chunk in response.iter_content(CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.maximum_size or time.monotonic() - start > self.maximum_seconds:
                        raise AttachmentError("Attachment transfer limit exceeded")
                    checksum.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            value = checksum.hexdigest()
            if not size or (declared is not None and size != int(declared)):
                raise AttachmentError("Attachment download was empty or incomplete")
            if (expected_size is not None and size != expected_size) or (expected_hash is not None and value != expected_hash):
                raise AttachmentError("Remote attachment bytes differ from the preserved source")
            destination = Path(directory) / value
            os.replace(temporary, destination)
            temporary = None
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            name = re.sub(r"[^A-Za-z0-9._-]", "_", unquote(urlsplit(url).path.rsplit("/", 1)[-1]))[:150]
            if not name or "." not in name:
                name = f"attachment-{value[:16]}{mimetypes.guess_extension(content_type) or '.bin'}"
            return {"size": size, "sha256": value, "filename": name, "content_type": content_type, "local_path": str(destination)}
        finally:
            response.close()
            if temporary is not None:
                os.unlink(temporary)

    def check_identity(self):
        response = self.api("GET", "users/me")
        try:
            if response.json().get("id") not in self.settings.importers:
                raise AttachmentError("Attachment token must belong to the configured importer")
        finally:
            response.close()

    def download_source(self, url, directory):
        if not source_url(url):
            raise AttachmentError("Unsupported original attachment URL")
        return self._download(url, directory, source=True)

    def allocate(self, path, metadata, external_id):
        response = self.api("POST", path, {"name": metadata["filename"], "type": metadata["content_type"],
                                           "size": metadata["size"], "external_source": "github", "external_id": external_id})
        try:
            return response.json()
        finally:
            response.close()

    def validate_upload(self, upload_data, metadata):
        url = upload_data["url"]
        if _origin(url) not in self.storage_origins:
            raise AttachmentError("Storage upload origin is not approved")
        path = Path(metadata["local_path"])
        checksum = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK_SIZE):
                checksum.update(chunk)
        if path.stat().st_size != metadata["size"] or checksum.hexdigest() != metadata["sha256"]:
            raise AttachmentError("Private attachment changed before upload")
    def upload(self, upload_data, metadata):
        self.validate_upload(upload_data, metadata)
        url, fields = upload_data["url"], upload_data["fields"]
        path = Path(metadata["local_path"])
        body = Multipart(fields, path, metadata["filename"], metadata["content_type"], self.maximum_seconds)
        response = self._request("POST", url, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={body.boundary}", "Content-Length": str(len(body)),
        })
        try:
            if response.status_code not in {200, 201, 204}:
                raise AttachmentError("Storage upload was not confirmed")
        finally:
            response.close()

    def confirm(self, path):
        response = self.api("PATCH", path, {"is_uploaded": True}, accepted=(204,))
        response.close()

    def verify_asset(self, path, asset_id, metadata, directory, external_id):
        response = self.api("GET", path)
        try:
            records = response.json()
        finally:
            response.close()
        matching = [record for record in records if record.get("id") == asset_id]
        if len(matching) != 1:
            raise AttachmentError("Uploaded attachment is absent from remote readback")
        record = matching[0]
        issue_id = path.rstrip("/").split("/")[-2]
        if (record.get("issue") != issue_id or record.get("project") != self.settings.project
                or record.get("created_by") not in self.settings.importers or record.get("is_uploaded") is not True
                or record.get("external_source") != "github" or record.get("external_id") != external_id
                or record.get("size") != metadata["size"]):
            raise AttachmentError("Remote attachment identity or metadata did not match")
        response = self.api("GET", f"{path}/{asset_id}", accepted=(302,))
        try:
            url = response.headers.get("Location")
            if not url:
                raise AttachmentError("Attachment download redirect is missing")
        finally:
            response.close()
        self._download(urljoin(self.settings.base_url, url), directory,
                       expected_size=metadata["size"], expected_hash=metadata["sha256"])


def transfer_all(ledger, transfer):
    """Advance durable upload stages and require remote byte equality for completion."""
    if transfer.settings.project != ledger.project_id or transfer.settings.resource != "work-items" or not transfer.settings.writes_enabled:
        raise AttachmentError("Attachment migration requires enabled writes to the configured project")
    if ledger.db.execute("SELECT 1 FROM attachments WHERE stage='removed'").fetchone():
        raise AttachmentError("A migrated attachment reference was removed; explicit archival reconciliation required")
    transfer.check_identity()
    directory = Path(ledger.db.execute("PRAGMA database_list").fetchone()[2]).parent
    names = ("source_key", "source_url", "stage", "size", "sha256", "filename", "content_type", "local_path", "asset_id", "upload_data")
    records = [dict(zip(names, row)) for row in ledger.db.execute("SELECT * FROM attachments WHERE stage!='omitted' ORDER BY source_key,source_url")]
    for record in records:
        key, url = record["source_key"], record["source_url"]
        row = ledger.db.execute("SELECT plane_id FROM objects WHERE source_key=? AND kind='issue' AND status='complete'", (key,)).fetchone()
        if row is None:
            raise AttachmentError("Attachment parent has no confirmed imported issue")
        path = f"workspaces/{transfer.settings.workspace}/projects/{ledger.project_id}/work-items/{UUID(row[0])}/attachments"
        external_id = hashlib.sha256(f"{key}\n{url}".encode()).hexdigest()

        def advance(stage, **values):
            expected = record["stage"]
            columns = ["stage", *values]
            with ledger.db:
                changed = ledger.db.execute(f"UPDATE attachments SET {','.join(column+'=?' for column in columns)} WHERE source_key=? AND source_url=? AND stage=?",
                                            (stage, *values.values(), key, url, expected)).rowcount
            if changed != 1:
                raise AttachmentError("Another importer owns this attachment operation")
            record.update(stage=stage, **values)

        if record["stage"] == "planned":
            advance("downloaded", **transfer.download_source(url, directory))
        if record["stage"] in {"allocation_pending", "upload_pending"}:
            raise AttachmentError("Attachment write outcome is uncertain; automatic replay blocked")
        if record["stage"] == "downloaded":
            advance("allocation_pending")
            result = transfer.allocate(path, record, external_id)
            asset_id = str(UUID(result["asset_id"]))
            attachment = result["attachment"]
            if (attachment.get("id") != asset_id or attachment.get("issue") != row[0]
                    or attachment.get("project") != ledger.project_id or attachment.get("size") != record["size"]
                    or attachment.get("created_by") not in transfer.settings.importers
                    or attachment.get("external_id") != external_id or attachment.get("external_source") != "github"):
                raise AttachmentError("Allocated attachment did not match its intended scope")
            advance("allocated", asset_id=asset_id, upload_data=json.dumps(result["upload_data"]))
        if record["stage"] == "allocated":
            transfer.validate_upload(json.loads(record["upload_data"]), record)
            advance("upload_pending")
            transfer.upload(json.loads(record["upload_data"]), record)
            advance("uploaded", upload_data=None)
        if record["stage"] == "uploaded":
            advance("confirmation_pending")
            transfer.confirm(f"{path}/{record['asset_id']}")
            advance("confirmed")
        if record["stage"] in {"confirmation_pending", "confirmed", "verified"}:
            transfer.verify_asset(path, record["asset_id"], record, directory, external_id)
            advance("verified")


def counts(db):
    return dict(db.execute("SELECT stage,count(*) FROM attachments GROUP BY stage"))
