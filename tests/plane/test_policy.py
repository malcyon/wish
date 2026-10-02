"""Check that untrusted ticket text cannot bypass filtering or write safeguards."""
import json

import pytest

from tools.plane.client import Client
from tools.plane.policy import Journal, PlaneError, Policy, Settings, digest

AGENT = '00000000-0000-0000-0000-000000000001'
OUTSIDE = '00000000-0000-0000-0000-000000000002'
IMPORTER = '00000000-0000-0000-0000-000000000003'
PROJECT = '00000000-0000-0000-0000-000000000004'
ITEM = '00000000-0000-0000-0000-000000000005'
STATE = '00000000-0000-0000-0000-000000000006'
LABEL = '00000000-0000-0000-0000-000000000007'


def settings(tmp_path, **overrides):
    data = dict(base_url='https://plane.example', workspace_slug='wish', project_id=PROJECT,
                agent_account_id=AGENT, trusted_account_ids=[AGENT], importer_account_ids=[IMPORTER],
                token_file=str(tmp_path / 'token'), journal_file=str(tmp_path / 'journal.sqlite'),
                source_trusted_account_ids=['github:42'], writes_enabled=True)
    data.update(overrides)
    return Settings(data)


def record(**overrides):
    result = dict(id=ITEM, sequence_id=1, created_by=AGENT, name='Ticket',
                  description_html='<p>Evidence</p>', state=STATE, labels=[], priority='high')
    result.update(overrides)
    return result


class Fake:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(self, method, path, data=None, params=None):
        self.calls.append((method, path, data, params))
        return self.handler(method, path, data, params)


@pytest.mark.parametrize('author', [OUTSIDE, None, {'id': OUTSIDE, 'display_name': 'Donald'}])
def test_outside_titles_bodies_and_unknown_fields_never_escape(tmp_path, author):
    policy = Policy(settings(tmp_path))
    result = policy.filtered(record(created_by=author, name='SECRET', description_html='SECRET', extra='SECRET'))
    assert 'SECRET' not in json.dumps(result)
    assert result['trusted'] is False
    assert 'Withheld' in policy.citation(result)


def test_unknown_editor_withholds_trusted_author_text(tmp_path):
    assert not Policy(settings(tmp_path)).filtered(record(updated_by=OUTSIDE))['trusted']


def test_importer_requires_protected_matching_provenance(tmp_path):
    config = settings(tmp_path)
    policy = Policy(config)
    imported = record(created_by=IMPORTER)
    assert not policy.trusted(imported)
    config.provenance[ITEM] = {'text_sha256': digest(imported), 'original_account_id': 'github:42'}
    assert policy.trusted(imported)
    assert not policy.trusted({**imported, 'name': 'Injected replacement'})
    config.provenance[ITEM]['original_account_id'] = 'github:99'
    assert not policy.trusted(imported)


def test_mutable_record_provenance_does_not_grant_trust(tmp_path):
    assert not Policy(settings(tmp_path)).trusted(record(created_by=IMPORTER, original_account_id=AGENT, trusted=True))


def test_complete_pagination_and_local_search_do_not_leak_withheld_text(tmp_path):
    def handle(method, path, data, params):
        if params.get('cursor'):
            return {'results': [record(id=OUTSIDE, sequence_id=2, created_by=OUTSIDE, name='SECRET')], 'next_page_results': False}
        return {'results': [record()], 'next_page_results': True, 'next_cursor': '100:1:0'}
    fake = Fake(handle)
    client = Client(settings(tmp_path), fake)
    assert len(client.list()) == 2
    assert client.list('SECRET') == []
    assert fake.calls[1][3]['cursor'] == '100:1:0'


@pytest.mark.parametrize('response', [
    {'results': []},
    {'results': [], 'next_page_results': True},
    {'results': [], 'next_page_results': True, 'next_cursor': 'repeat'},
])
def test_invalid_pagination_fails_instead_of_claiming_complete_list(tmp_path, response):
    with pytest.raises(PlaneError):
        Client(settings(tmp_path), Fake(lambda *args: response)).list()


def test_comments_are_paginated_and_filtered(tmp_path):
    def handle(method, path, data, params):
        if path.endswith('/comments'):
            if params.get('cursor'):
                return {'results': [dict(id=OUTSIDE, created_by=OUTSIDE, comment_html='SECRET')], 'next_page_results': False}
            return {'results': [dict(id=IMPORTER, created_by=AGENT, comment_html='Known')], 'next_page_results': True, 'next_cursor': 'next'}
        return record()
    result = Client(settings(tmp_path), Fake(handle)).read(ITEM)
    assert len(result['comments']) == 2
    assert 'SECRET' not in json.dumps(result)


def test_human_label_from_later_page_blocks_all_writes(tmp_path):
    def handle(method, path, data, params):
        assert method == 'GET'
        if path == 'users/me':
            return {'id': AGENT}
        if path.endswith('/labels'):
            if params.get('cursor'):
                return {'results': [{'id': LABEL, 'name': 'human'}], 'next_page_results': False}
            return {'results': [], 'next_page_results': True, 'next_cursor': 'next'}
        return record(labels=[LABEL])
    client = Client(settings(tmp_path), Fake(handle))
    with pytest.raises(PlaneError, match='human threads'):
        client.comment('test', ITEM, 'A comment')


def test_disabled_writes_make_no_network_calls(tmp_path):
    fake = Fake(lambda *args: pytest.fail('Network used'))
    with pytest.raises(PlaneError, match='disabled'):
        Client(settings(tmp_path, writes_enabled=False), fake).comment('test', ITEM, 'Text')


def test_wrong_account_cannot_write(tmp_path):
    fake = Fake(lambda *args: {'id': OUTSIDE})
    with pytest.raises(PlaneError, match='credential'):
        Client(settings(tmp_path), fake).comment('test', ITEM, 'Text')
    assert len(fake.calls) == 1


def test_timeout_prevents_duplicates_across_process_restart_and_new_id(tmp_path):
    path = tmp_path / 'writes.sqlite'
    def timeout():
        raise TimeoutError('Server might have accepted it')
    with pytest.raises(TimeoutError):
        Journal(path).run('original', {'payload': 'Text'}, timeout)
    for key in ['original', 'different']:
        with pytest.raises(PlaneError, match='uncertain'):
            Journal(path).run(key, {'payload': 'Text'}, lambda: pytest.fail('Duplicate write'))


def test_completed_writes_reuse_result_and_reject_changed_payload(tmp_path):
    journal = Journal(tmp_path / 'writes.sqlite')
    assert journal.run('write', {'body': 'Text'}, lambda: {'id': ITEM}) == {'id': ITEM}
    assert journal.run('write', {'body': 'Text'}, lambda: pytest.fail('Duplicate')) == {'id': ITEM}
    with pytest.raises(PlaneError, match='different write'):
        journal.run('write', {'body': 'Changed'}, lambda: pytest.fail('Reused key'))


@pytest.mark.parametrize('base_url', ['http://plane.example', 'https://u:p@plane.example', 'https://plane.example/api', 'https://plane.example?secret=x'])
def test_credential_destination_is_exact_https_origin(tmp_path, base_url):
    with pytest.raises(PlaneError):
        settings(tmp_path, base_url=base_url)


def test_controls_and_markdown_cannot_change_citation_target(tmp_path):
    policy = Policy(settings(tmp_path))
    result = policy.filtered(record(name='Title\x1b[31m [Click](https://outside)'))
    citation = policy.citation(result)
    assert '\x1b' not in citation
    assert '\\[Click\\]\\(' in citation
    assert citation.endswith(f'/issues/{ITEM})')


def test_token_requires_private_permissions(tmp_path):
    config = settings(tmp_path)
    config.token_file.write_text('Secret')
    config.token_file.chmod(0o644)
    with pytest.raises(PlaneError, match='0600'):
        config.token()
    config.token_file.chmod(0o600)
    assert config.token() == 'Secret'


def test_ai_label_does_not_grant_author_trust(tmp_path):
    filtered = Policy(settings(tmp_path)).filtered(record(created_by=OUTSIDE, labels=[{'id': LABEL, 'name': 'AI'}]))
    assert filtered['trusted'] is False


def test_update_requires_explanation_before_mutating(tmp_path):
    def handle(method, path, data, params):
        assert method == 'GET'
        if path == 'users/me':
            return {'id': AGENT}
        if path.endswith('/labels'):
            return []
        return record()
    with pytest.raises(PlaneError, match='Nonempty'):
        Client(settings(tmp_path), Fake(handle)).update('edit', ITEM, {'priority': 'low'}, '')


def test_correction_comment_is_after_patch_and_state_is_read_back(tmp_path):
    current = record()
    def handle(method, path, data, params):
        if path == 'users/me':
            return {'id': AGENT}
        if path.endswith('/labels'):
            return []
        if path.endswith('/comments'):
            if method == 'POST':
                assert current['priority'] == 'low'
                return {'id': OUTSIDE, 'created_by': AGENT, **data}
            return {'results': [], 'next_page_results': False}
        if method == 'PATCH':
            current.update(data)
        return dict(current)
    fake = Fake(handle)
    result = Client(settings(tmp_path), fake).update('edit', ITEM, {'priority': 'low'}, 'Evidence changed')
    assert result['priority'] == 'low'
    assert [c[0] for c in fake.calls if c[0] != 'GET'] == ['PATCH', 'POST']


def test_state_change_with_wrong_readback_is_not_reported_complete(tmp_path):
    def handle(method, path, data, params):
        if path == 'users/me':
            return {'id': AGENT}
        if path.endswith('/labels'):
            return []
        if path.endswith('/states'):
            return [{'id': OUTSIDE, 'name': 'Done', 'group': 'completed'}]
        if path.endswith('/comments'):
            if method == 'POST':
                return {'id': OUTSIDE, 'created_by': AGENT, **data}
            return {'results': [], 'next_page_results': False}
        return record()
    with pytest.raises(PlaneError, match='readback'):
        Client(settings(tmp_path), Fake(handle)).update('close', ITEM, {'state': OUTSIDE}, 'Evidence and CI recorded')


@pytest.mark.parametrize('provenance', [None, {'human_thread': True}])
def test_imported_human_origin_cannot_be_removed_by_changing_labels(tmp_path, provenance):
    config = settings(tmp_path)
    if provenance:
        config.provenance[ITEM] = provenance
    def handle(method, path, data, params):
        assert method == 'GET'
        if path == 'users/me':
            return {'id': AGENT}
        return record(created_by=IMPORTER, labels=[])
    with pytest.raises(PlaneError, match='human threads|protected provenance'):
        Client(config, Fake(handle)).comment('comment', ITEM, 'Text')


def test_transport_never_follows_redirects_or_reveals_server_error_text(monkeypatch):
    import sys
    from types import SimpleNamespace

    from tools.plane.client import Transport
    calls = []
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(RequestException=OSError))
    def request(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=302, headers={'Location': 'https://outside'}, text='SecretToken')
    transport = object.__new__(Transport)
    transport.resource = SimpleNamespace(session=SimpleNamespace(request=request),
                                        _build_url=lambda p: 'https://plane.example/' + p,
                                        _headers=lambda: {'X-Api-Key': 'SecretToken'})
    with pytest.raises(PlaneError) as failure:
        transport.request('POST', 'tickets', {'name': 'Example'})
    assert 'SecretToken' not in str(failure.value)
    assert calls[0]['allow_redirects'] is False
    assert len(calls) == 1


@pytest.mark.parametrize('method,expected_calls', [('GET', 2), ('POST', 1), ('PATCH', 1)])
def test_rate_limit_waits_only_on_reads(monkeypatch, method, expected_calls):
    import sys
    from types import SimpleNamespace

    from tools.plane.client import Transport
    calls = []
    sleeps = []
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(RequestException=OSError))
    monkeypatch.setattr('tools.plane.client.time.sleep', sleeps.append)
    def request(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(status_code=429, headers={'Retry-After': '2'})
        return SimpleNamespace(status_code=200, json=lambda: {'id': ITEM})
    transport = object.__new__(Transport)
    transport.resource = SimpleNamespace(session=SimpleNamespace(request=request),
                                        _build_url=lambda p: 'https://plane.example/' + p,
                                        _headers=lambda: {})
    if method == 'GET':
        assert transport.request(method, 'tickets') == {'id': ITEM}
        assert sleeps == [2]
    else:
        with pytest.raises(PlaneError, match='rate limit'):
            transport.request(method, 'tickets')
        assert not sleeps
    assert len(calls) == expected_calls


def test_http_requires_explicit_boolean_authorization(tmp_path):
    for permission in (False, 'true', 1, None):
        with pytest.raises(PlaneError):
            settings(tmp_path, base_url='http://plane.example', allow_insecure_http=permission)
    assert settings(tmp_path, base_url='http://plane.example', allow_insecure_http=True).base_url == 'http://plane.example'
    with pytest.raises(PlaneError):
        settings(tmp_path, base_url='http://user:secret@plane.example', allow_insecure_http=True)
