"""Project Plane records and constrain ticket writes to the configured project."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


class PlaneError(Exception):
    """A Plane operation could not be completed safely."""


class PlaneHttpError(PlaneError):
    """Plane answered with an error status, so the request was not applied."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class PlaneNotSent(PlaneError):
    """The request never reached Plane, for example a refused connection or a failed name lookup."""


def uuid(value):
    """Require a canonical account or record identifier."""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PlaneError("Expected a UUID") from exc


def private_json(path):
    """Read a local configuration file without accepting shared writable files."""
    path = Path(path)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
        raise PlaneError("Policy files must be owned by this account and not writable by others")
    return json.loads(path.read_text())


def clean(value):
    """Remove terminal controls while preserving body line breaks."""
    return ''.join(c for c in str(value or '') if c == '\n' or not unicodedata.category(c).startswith('C'))


class Settings:
    """Validate the local allowlist and private credential locations."""

    def __init__(self, data):
        self.base_url = data['base_url'].rstrip('/')
        parsed = urlsplit(self.base_url)
        allowed_schemes = {'https', 'http'} if data.get('allow_insecure_http') is True else {'https'}
        if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise PlaneError("Plane base URL must be an HTTPS origin unless HTTP is explicitly authorized")
        self.workspace = data['workspace_slug']
        self.identifier = data.get('project_identifier', 'WISH')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', self.workspace) or not re.fullmatch(r'[A-Z][A-Z0-9]*', self.identifier):
            raise PlaneError("Invalid workspace or project identifier")
        self.project = uuid(data['project_id'])
        self.agent = uuid(data['agent_account_id'])
        self.token_file = Path(data['token_file'])
        self.journal_file = Path(data['journal_file'])
        self.writes_enabled = data.get('writes_enabled') is True
        self.resource = data.get('resource', 'work-items')
        if self.resource not in {'work-items', 'issues'}:
            raise PlaneError("Unsupported Plane API resource")

    @classmethod
    def load(cls):
        """Load the configuration named by the secret-free launcher."""
        path = os.environ.get('WISH_PLANE_CONFIG')
        if not path:
            raise PlaneError("Set WISH_PLANE_CONFIG to a private configuration file")
        return cls(private_json(path))

    def token(self):
        """Read an owner-only token without passing it in command arguments."""
        info = self.token_file.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise PlaneError("Plane token file must be owned by this account with mode 0600")
        token = self.token_file.read_text().strip()
        if not token or '\n' in token or '\r' in token:
            raise PlaneError("Plane token file is empty or invalid")
        return token


class Policy:
    """Expose project ticket text and metadata with safe terminal characters."""

    def __init__(self, settings):
        self.settings = settings

    def author(self, record):
        author = record.get('created_by')
        if isinstance(author, dict):
            author = author.get('id')
        try:
            return uuid(author)
        except PlaneError:
            return None

    def trusted(self, record):
        """Mark private Plane text readable without treating it as instructions."""
        return True

    def filtered(self, record, comment=False):
        out = {'id': uuid(record['id']), 'author_id': self.author(record), 'trusted': self.trusted(record)}
        for field in ('created_at', 'updated_at'):
            out[field] = clean(record.get(field))
        for field in (('comment_html',) if comment else ('name', 'description_html')):
            text = str(record.get(field) or '')
            out[field] = clean(text)
        if not comment:
            sequence = record.get('sequence_id')
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise PlaneError("Plane returned an invalid sequence number")
            out.update(sequence_id=sequence, identifier=f'{self.settings.identifier}-{sequence}',
                       priority=record.get('priority') if record.get('priority') in {'high', 'medium', 'low', 'urgent', 'none'} else None,
                       state=uuid(record['state']['id'] if isinstance(record.get('state'), dict) else record.get('state')),
                       labels=[uuid(v['id'] if isinstance(v, dict) else v) for v in record.get('labels', [])])
            out['url'] = f'{self.settings.base_url}/{self.settings.workspace}/projects/{self.settings.project}/issues/{out["id"]}'
        return out

    def compact(self, record):
        """Summarise a written ticket without its description or comments."""
        full = self.filtered(record)
        return {k: full[k] for k in ('id', 'identifier', 'name', 'state', 'priority', 'labels', 'author_id')}

    def compact_comment(self, record):
        """Summarise a written comment without its body."""
        full = self.filtered(record, comment=True)
        return {k: full[k] for k in ('id', 'author_id', 'created_at')}

    def citation(self, filtered):
        title = ' '.join(filtered['name'].split())
        title = re.sub(r'([\\\[\]()`*_<>])', r'\\\1', title)
        return f'[{filtered["identifier"]} ({title})]({filtered["url"]})'


class Journal:
    """Reserve each logical write before sending it and never replay uncertain writes."""

    # A busy writer is waited for rather than failed, because several agents share one journal.
    BUSY_SECONDS = 60

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        if path.stat().st_mode & 0o077:
            raise PlaneError("Write journal must have mode 0600")
        self.path = path
        with self._db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS writes (key TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, status TEXT, result TEXT)')
            if 'request' not in {row[1] for row in db.execute('PRAGMA table_info(writes)')}:
                db.execute('ALTER TABLE writes ADD COLUMN request TEXT')
        for suffix in ('-wal', '-shm'):
            side = Path(str(path) + suffix)
            if side.exists() and side.stat().st_mode & 0o077:
                raise PlaneError("Write journal side files must have mode 0600")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=self.BUSY_SECONDS)
        try:
            with db:
                yield db
        finally:
            db.close()

    def run(self, key, request, send):
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', key):
            raise PlaneError("A stable operation ID is required")
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT fingerprint,status,result,key FROM writes WHERE key=? OR fingerprint=?', (key, fingerprint)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise PlaneError("Operation ID was already used for a different write")
                if prior[1] == 'done':
                    return json.loads(prior[2])
                if prior[1] != 'unsent':
                    raise PlaneError("Write outcome is uncertain; reconcile the durable journal before another attempt")
                key = prior[3]
                db.execute('UPDATE writes SET status=? WHERE key=?', ('pending', key))
            else:
                db.execute('INSERT INTO writes (key,fingerprint,status,result,request) VALUES (?,?,?,NULL,?)',
                           (key, fingerprint, 'pending', json.dumps(request)))
        try:
            result = send()
        except (PlaneHttpError, PlaneNotSent):
            self._finish(key, 'unsent', None)
            raise
        self._finish(key, 'done', result)
        return result

    def _finish(self, key, status, result):
        with self._db() as db:
            db.execute('UPDATE writes SET status=?,result=? WHERE key=? AND status=?',
                       (status, None if result is None else json.dumps(result), key, 'pending'))

    def reconcile(self, key, decide):
        """Settle a pending key from `decide(request)`, which returns the result if the write is present and None if it is not."""
        with self._db() as db:
            row = db.execute('SELECT status,result,request FROM writes WHERE key=?', (key,)).fetchone()
        if row is None:
            raise PlaneError("No journal entry has this operation ID")
        status, result, request = row
        if status != 'pending':
            return {'operation_id': key, 'status': status, 'result': json.loads(result) if result else None}
        if request is None:
            raise PlaneError("This journal entry predates stored requests, so it cannot be decided; it is unchanged")
        found = decide(json.loads(request))
        if found is None:
            self._finish(key, 'unsent', None)
            return {'operation_id': key, 'status': 'unsent', 'result': None}
        self._finish(key, 'done', found)
        return {'operation_id': key, 'status': 'done', 'result': found}


def paragraph(text):
    """Render supplied Markdown as HTML; raw HTML stays escaped and unsafe link schemes are not linked."""
    if not isinstance(text, str) or not text.strip():
        raise PlaneError("Nonempty text is required")
    from markdown_it import MarkdownIt
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True}).enable('table')
    return renderer.render(text).strip()
