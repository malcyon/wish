"""Check exported MCP read permissions and the policy behind exposed tools."""
import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from tools.plane.client import Client
from tools.plane.mcp import build_server
from tools.plane.policy import Settings

AGENT = '00000000-0000-0000-0000-000000000001'
OUTSIDE = '00000000-0000-0000-0000-000000000002'
PROJECT = '00000000-0000-0000-0000-000000000003'
ITEM = '00000000-0000-0000-0000-000000000004'
STATE = '00000000-0000-0000-0000-000000000005'
READ_TOOLS = {'list_tickets', 'read_ticket', 'cite_ticket', 'project_metadata'}
WRITE_TOOLS = {'create_ticket', 'comment_ticket', 'update_ticket'}


class Transport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, data=None, params=None):
        self.calls.append((method, path))
        assert method == 'GET'
        record = dict(id=ITEM, sequence_id=1, created_by=OUTSIDE, updated_by=OUTSIDE,
                      name='SECRET TITLE', description_html='<p>SECRET BODY</p>',
                      state=STATE, labels=[], priority='high')
        if path.endswith('/comments'):
            rows = [dict(id=OUTSIDE, created_by=OUTSIDE, updated_by=OUTSIDE,
                         comment_html='<p>SECRET COMMENT</p>')]
        elif path.endswith('/states'):
            rows = [dict(id=STATE, name='Backlog', group='backlog')]
        elif path.endswith('/labels'):
            rows = []
        elif path.endswith('/' + ITEM):
            return record
        else:
            rows = [record]
        return {'results': rows, 'next_page_results': False}


@pytest.fixture
def adapter(tmp_path):
    settings = Settings(dict(base_url='https://plane.example', workspace_slug='wish',
                             project_id=PROJECT, agent_account_id=AGENT,
                             trusted_account_ids=[AGENT], token_file=str(tmp_path / 'token'),
                             journal_file=str(tmp_path / 'journal.sqlite'), writes_enabled=False))
    transport = Transport()
    return build_server(Client(settings, transport)), transport


def test_exported_mcp_reads_are_read_only_without_granting_write_tools(adapter):
    server, _ = adapter
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools.keys() == READ_TOOLS | WRITE_TOOLS
    for name in READ_TOOLS:
        assert tools[name].annotations is not None, name
        assert tools[name].annotations.readOnlyHint is True, name
    for name in WRITE_TOOLS:
        assert tools[name].annotations is None or tools[name].annotations.readOnlyHint is not True, name


@pytest.mark.parametrize('name', sorted(READ_TOOLS))
def test_mcp_read_calls_preserve_filtering_and_send_only_get_requests(adapter, name):
    server, transport = adapter
    arguments = {'identifier': 'WISH-1'} if name in {'read_ticket', 'cite_ticket'} else {}
    response = asyncio.run(server.call_tool(name, arguments))
    assert 'SECRET' not in str(response)
    if name != 'project_metadata':
        assert 'Withheld' in str(response)
    assert transport.calls
    assert all(method == 'GET' for method, _ in transport.calls)


def test_mcp_create_stops_at_disabled_write_guard_without_sending_a_request(adapter):
    server, transport = adapter
    with pytest.raises(ToolError, match='Plane writes are disabled pending deployment acceptance'):
        asyncio.run(server.call_tool('create_ticket', dict(operation_id='disabled-probe',
                                                         title='Ticket', body='Body',
                                                         priority='high', labels=[])))
    assert transport.calls == []
