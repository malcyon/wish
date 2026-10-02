"""Filter Plane records and constrain ticket writes to the configured project."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import stat
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


class PlaneError(Exception):
    """A Plane operation could not be completed safely."""


def uuid(value):
    """Require a canonical account or record identifier."""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PlaneError("Expected a UUID") from exc


def private_json(path):
    """Read local policy or provenance without accepting shared writable files."""
    path = Path(path)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
        raise PlaneError("Policy files must be owned by this account and not writable by others")
    return json.loads(path.read_text())


def clean(value):
    """Remove terminal controls while preserving body line breaks."""
    return ''.join(c for c in str(value or '') if c == '\n' or not unicodedata.category(c).startswith('C'))


def digest(record):
    """Bind imported authorship to the exact text being displayed."""
    values = {k: record.get(k) for k in ('name', 'description_html', 'comment_html')}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


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
        self.trusted = {uuid(v) for v in data['trusted_account_ids']}
        self.importers = {uuid(v) for v in data.get('importer_account_ids', [])}
        self.source_trusted = set(data.get('source_trusted_account_ids', []))
        if any(not re.fullmatch(r'github:[0-9]+', v) for v in self.source_trusted):
            raise PlaneError('Source trust requires namespaced stable GitHub account IDs')
        self.token_file = Path(data['token_file'])
        self.journal_file = Path(data['journal_file'])
        self.provenance = private_json(data['provenance_file']) if data.get('provenance_file') else {}
        self.writes_enabled = data.get('writes_enabled') is True
        self.resource = data.get('resource', 'work-items')
        if self.resource not in {'work-items', 'issues'}:
            raise PlaneError("Unsupported Plane API resource")
        if self.agent not in self.trusted or self.agent in self.importers:
            raise PlaneError("Agent account must be trusted and separate from importer accounts")

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
    """Expose only approved fields and decide trust using stable account IDs."""

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
        author = self.author(record)
        entry = self.settings.provenance.get(str(record.get('id')))
        if author in self.settings.importers or entry is not None:
            return bool(entry and entry.get('text_sha256') == digest(record)
                        and entry.get('original_account_id') in self.settings.source_trusted)
        updater = record.get('updated_by')
        if isinstance(updater, dict):
            updater = updater.get('id')
        return author in self.settings.trusted and updater in self.settings.trusted

    def filtered(self, record, comment=False):
        trusted = self.trusted(record)
        out = {'id': uuid(record['id']), 'author_id': self.author(record), 'trusted': trusted}
        for field in ('created_at', 'updated_at'):
            out[field] = clean(record.get(field))
        for field in (('comment_html',) if comment else ('name', 'description_html')):
            text = str(record.get(field) or '')
            out[field] = clean(text) if trusted else f'[Withheld: {len(text)} characters]'
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

    def citation(self, filtered):
        title = ' '.join(filtered['name'].split())
        title = re.sub(r'([\\\[\]()`*_<>])', r'\\\1', title)
        return f'[{filtered["identifier"]} ({title})]({filtered["url"]})'


class Journal:
    """Reserve each logical write before sending it and never replay uncertain writes."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        if path.stat().st_mode & 0o077:
            raise PlaneError("Write journal must have mode 0600")
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS writes (key TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, status TEXT, result TEXT)')

    def run(self, key, request, send):
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', key):
            raise PlaneError("A stable operation ID is required")
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT fingerprint,status,result FROM writes WHERE key=? OR fingerprint=?', (key, fingerprint)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise PlaneError("Operation ID was already used for a different write")
                if prior[1] == 'done':
                    return json.loads(prior[2])
                raise PlaneError("Write outcome is uncertain; reconcile the durable journal before another attempt")
            db.execute('INSERT INTO writes VALUES (?,?,?,NULL)', (key, fingerprint, 'pending'))
        result = send()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE writes SET status=?,result=? WHERE key=?', ('done', json.dumps(result), key))
        return result


def paragraph(text):
    """Encode supplied prose as HTML without permitting embedded markup."""
    if not isinstance(text, str) or not text.strip():
        raise PlaneError("Nonempty text is required")
    return '<p>' + html.escape(text).replace('\n', '<br>') + '</p>'
