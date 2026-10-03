"""Prevent reduced CI from hiding executable changes anywhere in a push."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.suite.ci_route import classify

SCRIPT = Path(__file__).resolve().parents[2] / 'tools/suite/ci_route.py'


def git(repo, *args):
    return subprocess.run(
        ['git', *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def commit(repo, changes):
    for name, contents in changes.items():
        path = repo / name
        if contents is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding='utf-8')
    git(repo, 'add', '--all')
    git(repo, 'commit', '--allow-empty', '-m', 'Synthetic change')
    return git(repo, 'rev-parse', 'HEAD')


def event(base, head, **overrides):
    return dict(before=base, after=head, forced=False, created=False, deleted=False) | overrides


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '--initial-branch=main')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'commit.gpgsign', 'false')
    base = commit(tmp_path, {'README.md': 'Initial', 'docs/old.md': 'Old'})
    return tmp_path, base


def test_docs_add_edit_delete_across_commits(repo):
    root, base = repo
    commit(root, {'docs/new/note.md': 'First', 'docs/old.md': None})
    head = commit(root, {'docs/new/note.md': 'Second', 'docs/direct.md': 'Direct'})
    result = classify(root, event(base, head), 'push')
    assert result == dict(route='docs', base=base, head=head,
                          reason='Every pushed change is docs Markdown')


@pytest.mark.parametrize('name', [
    'README.md', '.claude/rules/words.md', '.github/workflows/test.yml',
    'docs/image.svg', 'docs/code.py', 'docs/note.MD', 'docs.md', 'code.py',
])
def test_any_non_docs_markdown_requires_full(repo, name):
    root, base = repo
    head = commit(root, {name: 'Changed', 'docs/note.md': 'Text'})
    assert classify(root, event(base, head), 'push')['route'] == 'full'


def test_intermediate_code_change_and_revert_requires_full(repo):
    root, base = repo
    commit(root, {'code.py': 'Temporary'})
    head = commit(root, {'code.py': None, 'docs/note.md': 'Text'})
    assert git(root, 'diff', '--name-only', base, head) == 'docs/note.md'
    assert classify(root, event(base, head), 'push')['route'] == 'full'


@pytest.mark.parametrize('source,target', [
    ('README.md', 'docs/moved.md'), ('docs/old.md', 'outside.md'),
])
def test_rename_across_docs_boundary_requires_full(repo, source, target):
    root, base = repo
    (root / source).rename(root / target)
    head = commit(root, {})
    assert classify(root, event(base, head), 'push')['route'] == 'full'


@pytest.mark.parametrize('code_on_branch', [False, True])
def test_merge_checks_changes_on_every_parent(repo, code_on_branch):
    root, base = repo
    git(root, 'switch', '-c', 'side')
    commit(root, {'code.py' if code_on_branch else 'docs/side.md': 'Side'})
    git(root, 'switch', 'main')
    commit(root, {'docs/main.md': 'Main'})
    git(root, 'merge', '--no-ff', 'side', '-m', 'Merge synthetic branch')
    head = git(root, 'rev-parse', 'HEAD')
    assert classify(root, event(base, head), 'push')['route'] == (
        'full' if code_on_branch else 'docs')


@pytest.mark.parametrize('overrides', [
    {'before': None}, {'before': 'f' * 40}, {'before': '0' * 40},
    {'after': '0' * 40}, {'before': '--help'}, {'forced': True},
    {'forced': None}, {'created': True}, {'deleted': True},
])
def test_uncertain_or_nonordinary_push_requires_full(repo, overrides):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    assert classify(root, event(base, head, **overrides), 'push')['route'] == 'full'


def test_rewritten_history_requires_full_even_without_forced_flag(repo):
    root, base = repo
    git(root, 'switch', '--orphan', 'unrelated')
    head = commit(root, {'docs/note.md': 'Text'})
    assert classify(root, event(base, head), 'push')['route'] == 'full'


def test_head_mismatch_and_empty_push_require_full(repo):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    assert classify(root, event(base, base), 'push')['route'] == 'full'
    assert classify(root, event(head, head), 'push')['route'] == 'full'
    empty = commit(root, {})
    assert classify(root, event(head, empty), 'push')['route'] == 'full'


@pytest.mark.parametrize('event_name', ['pull_request', 'schedule', 'workflow_dispatch', 'release', ''])
def test_only_push_can_reduce_ci(repo, event_name):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    assert classify(root, event(base, head), event_name)['route'] == 'full'


def test_force_full_and_missing_event_and_git_failure(repo, tmp_path):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    assert classify(root, event(base, head), 'push', force_full=True)['route'] == 'full'
    assert classify(root, None, 'push')['route'] == 'full'
    assert classify(root / 'missing', event(base, head), 'push')['route'] == 'full'


def test_shallow_repository_requires_full(repo, tmp_path):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    clone = tmp_path / 'clone'
    git(root, 'clone', '--depth=2', root.as_uri(), str(clone))
    assert classify(clone, event(base, head), 'push')['route'] == 'full'


def test_cli_requires_verified_docs_and_outputs_json(repo, tmp_path):
    root, base = repo
    head = commit(root, {'docs/note.md': 'Text'})
    payload = tmp_path / 'event.json'
    payload.write_text(json.dumps(event(base, head)), encoding='utf-8')
    command = [sys.executable, str(SCRIPT), '--repo', str(root),
               '--event-path', str(payload), '--event-name', 'push', '--require-docs']
    passed = subprocess.run(command, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stderr
    assert json.loads(passed.stdout)['route'] == 'docs'
    rejected = subprocess.run([*command, '--force-full'], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)['route'] == 'full'
    payload.write_text('{', encoding='utf-8')
    malformed = subprocess.run(command, capture_output=True, text=True)
    assert malformed.returncode != 0
    assert json.loads(malformed.stdout)['route'] == 'full'


def test_merge_parent_difference_requires_full_even_with_docs_only_final_diff(repo):
    root, original = repo
    git(root, 'branch', 'side', original)
    base = commit(root, {'code.py': 'Main code'})
    git(root, 'switch', 'side')
    commit(root, {'docs/side.md': 'Side docs'})
    git(root, 'switch', 'main')
    git(root, 'merge', '--no-ff', 'side', '-m', 'Merge synthetic branch')
    head = git(root, 'rev-parse', 'HEAD')
    assert git(root, 'diff', '--name-only', base, head) == 'docs/side.md'
    assert classify(root, event(base, head), 'push')['route'] == 'full'
