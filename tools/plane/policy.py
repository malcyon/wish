"""Project Plane records and constrain ticket writes to the configured project."""
from __future__ import annotations

import json
import os
import re
import stat
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


class PlaneError(Exception):
    """A Plane operation could not be completed safely."""


class PlaneHttpError(PlaneError):
    """Plane answered with a 4xx status, which rejects the request without applying it."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class PlaneNotSent(PlaneError):
    """The request never reached Plane, for example a refused connection or a failed name lookup."""


class PlaneOutcomeUnknown(PlaneError):
    """Plane may or may not have applied the write, as after a 5xx, a redirect or a read timeout."""


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


# The account the GitHub import posted as.
IMPORTER_ACCOUNT = 'bbca0246-1fb1-4715-8f6a-7926e4f023a9'


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
        self.importer = uuid(IMPORTER_ACCOUNT)
        self.token_file = Path(data['token_file'])
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


_DELIMITER_ROW = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$')
_FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
_QUOTE = re.compile(r'^(?:\s{0,3}>)*[ \t]*')
_CODE_SPAN = re.compile(r'(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)')


def _split_quote(line):
    """Split a line into its leading blockquote markers and the rest."""
    prefix = _QUOTE.match(line).group(0)
    return prefix, line[len(prefix):]


def _escape_code_pipes(line):
    """Escape a bare pipe inside a code span so a table cell is not split there."""
    def fix(match):
        body = re.sub(r'(?<!\\)\|', r'\\|', match.group(2))
        return f'{match.group(1)}{body}{match.group(1)}'
    return _CODE_SPAN.sub(fix, line)


def _protect_table_code(text):
    """Escape pipes inside code spans on table rows; fenced blocks and other text are untouched."""
    lines = text.split('\n')
    fence = None
    block = []

    def flush():
        # A table starts at the header line above its delimiter row and runs while rows hold a pipe;
        # prose above the header and text after the table keep their pipes.
        position = 1
        while position < len(block):
            _, delimiter = _split_quote(lines[block[position]])
            _, header = _split_quote(lines[block[position - 1]])
            if '|' in delimiter and '|' in header and _DELIMITER_ROW.match(delimiter):
                end = position - 1
                while end < len(block) and '|' in _split_quote(lines[block[end]])[1]:
                    prefix, rest = _split_quote(lines[block[end]])
                    lines[block[end]] = prefix + _escape_code_pipes(rest)
                    end += 1
                position = end + 1
            else:
                position += 1
        block.clear()

    for index, line in enumerate(lines):
        marker = _FENCE.match(line)
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            continue
        if marker:
            flush()
            fence = marker.group(1)
        elif line.strip():
            block.append(index)
        else:
            flush()
    flush()
    return '\n'.join(lines)


def paragraph(text):
    """Render supplied Markdown as HTML; raw HTML stays escaped and unsafe link schemes are not linked."""
    if not isinstance(text, str) or not text.strip():
        raise PlaneError("Nonempty text is required")
    from markdown_it import MarkdownIt
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True}).enable('table')
    return renderer.render(_protect_table_code(text)).strip()
