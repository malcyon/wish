"""Plane registration preserves client settings and never embeds credentials."""
from __future__ import annotations

import importlib.util
import json
import ssl
import sys
import tomllib
import urllib.request
from pathlib import Path

import pytest
import yaml

ROLE = Path(__file__).resolve().parents[2] / 'ansible/roles/agent-vm-guest'
SPEC = importlib.util.spec_from_file_location('plane_clients', ROLE / 'files/plane-clients.py')
clients = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clients)


def test_registration_preserves_settings_and_second_run_does_not_write(tmp_path, monkeypatch):
    claude = tmp_path / '.claude.json'
    claude.write_text(json.dumps({'theme': 'dark', 'mcpServers': {'vice': {'command': 'node'}}}))
    codex = tmp_path / '.codex/config.toml'
    codex.parent.mkdir()
    original = '# Keep comment\nmodel = "chosen"\n[mcp_servers.vice]\ncommand = "node"\n'
    codex.write_text(original)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv == ['/bin/codex', 'mcp', 'add', 'wish-plane', '--', '/bin/wish-plane']
        assert kwargs['env']['CODEX_HOME'] == str(codex.parent)
        codex.write_text(original + '\n[mcp_servers.wish-plane]\ncommand = "/bin/wish-plane"\n')

    monkeypatch.setattr(clients.subprocess, 'run', run)
    assert clients.register(tmp_path, '/bin/wish-plane', '/bin/codex')
    assert json.loads(claude.read_text()) == {
        'theme': 'dark', 'mcpServers': {'vice': {'command': 'node'},
        'wish-plane': {'type': 'stdio', 'command': '/bin/wish-plane', 'args': []}}}
    assert tomllib.loads(codex.read_text())['model'] == 'chosen'
    before = [path.stat().st_mtime_ns for path in (claude, codex)]
    assert not clients.register(tmp_path, '/bin/wish-plane', '/bin/codex')
    assert before == [path.stat().st_mtime_ns for path in (claude, codex)]
    assert len(calls) == 1


def test_invalid_codex_config_leaves_claude_untouched(tmp_path):
    claude = tmp_path / '.claude.json'
    claude.write_text('{"theme":"dark"}')
    codex = tmp_path / '.codex/config.toml'
    codex.parent.mkdir()
    codex.write_text('[')
    with pytest.raises(ValueError):
        clients.register(tmp_path, '/bin/wish-plane', '/bin/codex')
    assert claude.read_text() == '{"theme":"dark"}'


def test_provisioning_is_opt_in_and_credentials_are_private():
    defaults = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
    assert defaults['agent_guest_plane_enabled'] is False
    tasks = yaml.safe_load((ROLE / 'tasks/plane.yml').read_text())
    copies = [task for task in tasks if 'ansible.builtin.copy' in task]
    private = [task for task in copies if task.get('no_log')]
    assert len(private) == 2
    assert all(task['ansible.builtin.copy']['mode'] == '0600' for task in private)
    launcher = (ROLE / 'templates/wish-plane.sh.j2').read_text()
    assert 'tools.plane.mcp' in launcher
    assert 'plane-mcp-server' not in launcher
    assert 'PLANE_API_KEY' not in launcher
    assert 'REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt' in launcher


def test_codex_unrelated_change_fails_and_restores_original(tmp_path, monkeypatch):
    codex = tmp_path / '.codex/config.toml'
    codex.parent.mkdir()
    original = 'model="chosen"\n'
    codex.write_text(original)

    def run(*args, **kwargs):
        codex.write_text('model="lost"\n[mcp_servers.wish-plane]\ncommand="/bin/wish-plane"\n')

    monkeypatch.setattr(clients.subprocess, 'run', run)
    with pytest.raises(ValueError, match='preserve unrelated'):
        clients.register(tmp_path, '/bin/wish-plane', '/bin/codex')
    assert codex.read_text() == original
    assert not (tmp_path / '.claude.json').exists()


@pytest.mark.parametrize('origin', ['http://plane.morton.lan', 'https://plane.morton.lan'])
def test_access_probe_supports_http_without_disabling_https_verification(origin, monkeypatch):
    tasks = yaml.safe_load((ROLE / 'tasks/plane.yml').read_text())
    probe = next(task for task in tasks if task['name'].startswith('Check Plane access'))
    script = probe['ansible.builtin.command']['argv'][2]
    requests = []

    class Response:
        def close(self):
            requests.append('Closed')

    def urlopen(url, *, context, timeout):
        assert url == origin
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
        assert timeout == 15
        return Response()

    monkeypatch.setattr(sys, 'argv', ['probe', origin])
    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    exec(script, {})
    assert requests == ['Closed']


def test_http_is_explicit_and_does_not_require_a_certificate():
    defaults = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
    assert defaults['agent_guest_plane_allow_insecure_http'] is False
    assert defaults['agent_guest_plane_base_url'].startswith('https://')
    tasks = yaml.safe_load((ROLE / 'tasks/plane.yml').read_text())
    certificate_tasks = [task for task in tasks if task['name'] in {
        'Reject private keys in the public trust certificate',
        'Install the Plane public CA certificate', 'Refresh system certificate trust'}]
    assert len(certificate_tasks) == 3
    for task in certificate_tasks:
        conditions = task['when'] if isinstance(task['when'], list) else [task['when']]
        assert "agent_guest_plane_base_url.startswith('https://')" in conditions


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failure', ['command', 'timeout', 'invalid_toml'])
def test_failed_codex_registration_restores_file_and_permissions(tmp_path, monkeypatch, existing, failure):
    codex = tmp_path / '.codex/config.toml'
    codex.parent.mkdir()
    original = b'# Keep line endings\r\nmodel="chosen"\r\n'
    if existing:
        codex.write_bytes(original)
        codex.chmod(0o640)
    claude = tmp_path / '.claude.json'
    claude.write_text('{"theme":"dark"}')

    def run(*args, **kwargs):
        codex.write_text('[')
        codex.chmod(0o600)
        if failure == 'command':
            raise clients.subprocess.CalledProcessError(1, args[0])
        if failure == 'timeout':
            raise clients.subprocess.TimeoutExpired(args[0], 30)

    monkeypatch.setattr(clients.subprocess, 'run', run)
    with pytest.raises((ValueError, clients.subprocess.SubprocessError)):
        clients.register(tmp_path, '/bin/wish-plane', '/bin/codex')
    if existing:
        assert codex.read_bytes() == original
        assert codex.stat().st_mode & 0o777 == 0o640
    else:
        assert not codex.exists()
    assert claude.read_text() == '{"theme":"dark"}'
