"""Choose reduced CI only for verified pushes containing Markdown under docs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def classify(repo: Path, event: object, event_name: str, *, force_full=False) -> dict:
    """Inspect every pushed commit and default to full CI on uncertain history."""
    result = {'route': 'full', 'base': None, 'head': None, 'reason': ''}

    def full(reason):
        return {**result, 'reason': reason}

    if force_full:
        return full('Full CI requested')
    if event_name != 'push' or not isinstance(event, dict):
        return full('Only push events can use docs CI')
    for key, output in [('before', 'base'), ('after', 'head')]:
        value = event.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
            return full('Missing or invalid commit IDs')
        if value == '0' * 40:
            return full('Branch creation or deletion requires full CI')
        result[output] = value
    if any(event.get(key) is not False for key in ('forced', 'created', 'deleted')):
        return full('Missing or nonordinary push flags')

    def git(*args, input=None):
        return subprocess.run(
            ['git', *args], cwd=repo, input=input, capture_output=True,
            check=True, timeout=30,
        ).stdout

    base, head = result['base'], result['head']
    try:
        if git('rev-parse', '--is-shallow-repository').strip() != b'false':
            return full('Incomplete repository history')
        if git('rev-parse', 'HEAD').decode().strip() != head:
            return full('Event head does not match checkout')
        for commit in (base, head):
            if git('cat-file', '-t', commit).strip() != b'commit':
                return full('Event IDs must identify commits')
        git('merge-base', '--is-ancestor', base, head)
        commits = git('rev-list', f'{base}..{head}')
        if not commits.strip():
            return full('No pushed commits')
        # Separate merge-parent diffs retain code changes hidden by a final revert.
        changed = git(
            'diff-tree', '--stdin', '-r', '-m', '--root', '--no-renames',
            '--name-only', '--no-commit-id', '-z', input=commits,
        )
        paths = {name for name in changed.split(b'\0') if name}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return full('Git history could not be verified')
    if not paths:
        return full('No changed paths')
    if any(not (name.startswith(b'docs/') and name.endswith(b'.md'))
           for name in paths):
        return full('Push includes paths outside docs Markdown')
    return {**result, 'route': 'docs', 'reason': 'Every pushed change is docs Markdown'}


def main(argv=None):
    """Print the route and optionally require a verified docs-only push."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--event-path', type=Path, default=os.environ.get('GITHUB_EVENT_PATH'))
    parser.add_argument('--event-name', default=os.environ.get('GITHUB_EVENT_NAME', ''))
    parser.add_argument('--force-full', action='store_true')
    parser.add_argument('--require-docs', action='store_true')
    args = parser.parse_args(argv)
    try:
        event = json.loads(args.event_path.read_text(encoding='utf-8')) if args.event_path else None
    except (OSError, ValueError):
        event = None
    result = classify(args.repo, event, args.event_name, force_full=args.force_full)
    print(json.dumps(result, sort_keys=True))
    return int(args.require_docs and result['route'] != 'docs')


if __name__ == '__main__':
    raise SystemExit(main())
