"""Check the queue gap finder against fake tickets, ledgers and transcripts."""
import json
import os
import time

from tools.plane import queuegap

NOW = 1_000_000.0
IN_PROGRESS_IDLE = 'In Progress with no live agent: move to Queue, or Backlog if it waits on Donald'


def ticket(n, state='Queue', priority='high', group=None):
    group = group or {'Backlog': 'backlog', 'Queue': 'unstarted', 'In Progress': 'started', 'Completed': 'completed'}[state]
    return {'identifier': f'WISH-{n}', 'name': f'Title {n}', 'priority': priority, 'state': state, 'group': group}


def transcript(root, agent, age_minutes, session='s1'):
    path = root / session / 'subagents' / f'agent-{agent}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}\n')
    os.utime(path, (NOW - age_minutes * 60, NOW - age_minutes * 60))


def run(tmp_path, tickets, capsys, *argv):
    ledger = tmp_path / 'ledger.jsonl'
    code = queuegap.main(['--ledger', str(ledger), *argv], tickets=tickets, root=tmp_path / 'proj', now=NOW)
    assert code == 0
    return capsys.readouterr().out.splitlines()


def cli(tmp_path, *argv):
    assert queuegap.main(['--ledger', str(tmp_path / 'ledger.jsonl'), *argv]) == 0


def test_queue_and_in_progress_without_agent_or_reason_are_gaps(tmp_path, capsys):
    out = run(tmp_path, [ticket(1, 'Queue'), ticket(2, 'In Progress')], capsys, '--min-agents', '0')
    assert out == ['WISH-1 Queue high: no agent and no reason', 'WISH-2 In Progress high: ' + IN_PROGRESS_IDLE]


def test_backlog_gap_only_for_high_and_medium(tmp_path, capsys):
    tickets = [ticket(1, 'Backlog', 'high'), ticket(2, 'Backlog', 'medium'), ticket(3, 'Backlog', 'low'),
               ticket(4, 'Backlog', 'none'), ticket(5, 'Completed')]
    out = run(tmp_path, tickets, capsys, '--min-agents', '0')
    assert [line.split()[0] for line in out] == ['WISH-1', 'WISH-2']


def test_live_agent_clears_gap(tmp_path, capsys):
    transcript(tmp_path / 'proj', 'a1', 5)
    cli(tmp_path, 'assign', 'WISH-1', '--agent', 'a1')
    assert run(tmp_path, [ticket(1)], capsys, '--min-agents', '0') == ['No gaps.']


def test_done_and_stale_transcript_are_not_live(tmp_path, capsys):
    transcript(tmp_path / 'proj', 'old', 21)
    transcript(tmp_path / 'proj', 'fin', 1)
    cli(tmp_path, 'assign', 'WISH-1', '--agent', 'old')
    cli(tmp_path, 'assign', 'WISH-2', '--agent', 'fin')
    cli(tmp_path, 'done', 'fin')
    out = run(tmp_path, [ticket(1), ticket(2)], capsys, '--min-agents', '0')
    assert [line.split()[0] for line in out] == ['WISH-1', 'WISH-2']
    assert run(tmp_path, [ticket(1)], capsys, '--min-agents', '0', '--stale', '30') == ['No gaps.']


def test_missing_transcript_counts_live_and_is_marked(tmp_path, capsys):
    cli(tmp_path, 'assign', 'WISH-1', '--agent', 'ghost')
    out = run(tmp_path, [ticket(1), ticket(2)], capsys, '--min-agents', '8')
    assert out == ['WISH-2 Queue high: no agent and no reason', '1 live agents, below 8, 1 unconfirmed (?)']


def test_reason_clears_gap_and_later_assign_supersedes_it(tmp_path, capsys):
    cli(tmp_path, 'reason', 'WISH-1', 'waiting on Donald')
    assert run(tmp_path, [ticket(1), ticket(2, 'Backlog')], capsys, '--min-agents', '0') == ['WISH-2 Backlog high: backlog with no reason']
    cli(tmp_path, 'assign', 'WISH-1', '--agent', 'dead')
    cli(tmp_path, 'done', 'dead')
    assert run(tmp_path, [ticket(1)], capsys, '--min-agents', '0') == ['WISH-1 Queue high: no agent and no reason']
    cli(tmp_path, 'reason', 'WISH-1', 'again')
    cli(tmp_path, 'clear', 'WISH-1')
    assert len(run(tmp_path, [ticket(1)], capsys, '--min-agents', '0')) == 1


def test_below_minimum_line_only_when_a_gap_exists(tmp_path, capsys):
    assert run(tmp_path, [ticket(1)], capsys)[-1] == '0 live agents, below 8'
    assert run(tmp_path, [], capsys) == ['No gaps.']


def test_no_gaps_prints_one_line(tmp_path, capsys):
    assert run(tmp_path, [ticket(1, 'Completed'), ticket(2, 'Backlog', 'low')], capsys) == ['No gaps.']


def test_titles_and_json(tmp_path, capsys):
    assert run(tmp_path, [ticket(1)], capsys, '--min-agents', '0', '--titles') == ['WISH-1 Queue high: no agent and no reason (Title 1)']
    data = json.loads('\n'.join(run(tmp_path, [ticket(1)], capsys, '--min-agents', '0', '--json')))
    assert data['gaps'][0]['ticket'] == 'WISH-1' and data['live_agents'] == 0


def test_ledger_subcommands_append_json_lines(tmp_path):
    cli(tmp_path, 'assign', 'WISH-3', '--agent', 'x', '--lane', 'harness', '--role', 'junior-dev')
    cli(tmp_path, 'done', 'x')
    cli(tmp_path, 'reason', 'WISH-3', 'why')
    cli(tmp_path, 'clear', 'WISH-3')
    events = [json.loads(line) for line in (tmp_path / 'ledger.jsonl').read_text().splitlines()]
    assert [e['op'] for e in events] == ['assign', 'done', 'reason', 'clear']
    assert events[0]['lane'] == 'harness' and events[0]['role'] == 'junior-dev' and events[2]['text'] == 'why'
    assert abs(events[0]['at'] - time.time()) < 3600


def test_find_transcript_searches_every_session(tmp_path):
    transcript(tmp_path, 'abc', 1, session='second')
    assert queuegap.find_transcript('abc', tmp_path).parent.parent.name == 'second'
    assert queuegap.find_transcript('agent-abc', tmp_path) is not None
    assert queuegap.find_transcript('nope', tmp_path) is None


def test_replay_skips_torn_lines_and_missing_keys(tmp_path, capsys):
    ledger = tmp_path / 'ledger.jsonl'
    ledger.write_text('\n'.join([
        json.dumps({'op': 'assign', 'ticket': 'WISH-1', 'agent': 'a1'}),
        '{"op": "assign", "ticket": "WISH-2", "ag',
        json.dumps({'op': 'assign', 'ticket': 'WISH-3'}),
        json.dumps({'op': 'reason', 'ticket': 'WISH-4'}),
        json.dumps({'op': 'done'}),
        '[1, 2]',
        json.dumps({'op': 'reason', 'ticket': 'WISH-5', 'text': 'why'}),
    ]) + '\n')
    assigned, reasons, done = queuegap.replay(ledger)
    assert assigned == {'WISH-1': {'a1': {'lane': None, 'role': None}}}
    assert reasons == {'WISH-5': 'why'} and done == set()
    assert len(capsys.readouterr().err.splitlines()) == 5


def test_find_transcript_takes_the_newest_by_mtime(tmp_path):
    transcript(tmp_path, 'abc', 30, session='zzz-old')
    transcript(tmp_path, 'abc', 1, session='aaa-new')
    assert queuegap.find_transcript('abc', tmp_path).parent.parent.name == 'aaa-new'


def test_json_includes_titles_only_with_titles(tmp_path, capsys):
    plain = json.loads('\n'.join(run(tmp_path, [ticket(1)], capsys, '--min-agents', '0', '--json')))
    assert 'title' not in plain['gaps'][0]
    titled = json.loads('\n'.join(run(tmp_path, [ticket(1)], capsys, '--min-agents', '0', '--json', '--titles')))
    assert titled['gaps'][0]['title'] == 'Title 1'


def test_in_progress_with_no_live_agent_is_a_mismatch_whatever_its_reason(tmp_path, capsys):
    cli(tmp_path, 'reason', 'WISH-1', 'waiting on CI')
    out = run(tmp_path, [ticket(1, 'In Progress')], capsys, '--min-agents', '0')
    assert out == ['WISH-1 In Progress high: ' + IN_PROGRESS_IDLE]


def test_in_progress_waiting_on_donald_needs_backlog(tmp_path, capsys):
    cli(tmp_path, 'reason', 'WISH-1', 'Waiting on Donald to pick a wording')
    out = run(tmp_path, [ticket(1, 'In Progress')], capsys, '--min-agents', '0')
    assert out == ['WISH-1 In Progress high: In Progress waiting on Donald: move to Backlog']


def test_live_agent_clears_in_progress_mismatches(tmp_path, capsys):
    transcript(tmp_path / 'proj', 'a1', 5)
    cli(tmp_path, 'reason', 'WISH-1', 'waiting on Donald')
    cli(tmp_path, 'assign', 'WISH-1', '--agent', 'a1')
    cli(tmp_path, 'assign', 'WISH-2', '--agent', 'a1')
    assert run(tmp_path, [ticket(1, 'In Progress'), ticket(2, 'In Progress')], capsys, '--min-agents', '0') == ['No gaps.']
