#!/usr/bin/env python3
"""Print the tickets that have no live agent and no recorded reason, and In Progress tickets with no live agent.

The orchestrator records assignments and reasons in a local JSON-lines ledger
(never committed); Plane is only read.
"""
import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.registry.scratch import cache_dir

CLAUDE_PROJECT = Path.home() / '.claude' / 'projects' / '-home-agent-src-wish'
FINISHED_GROUPS = {'completed', 'cancelled'}
WATCHED_BACKLOG = {'urgent', 'high', 'medium'}


def default_ledger():
    return cache_dir('orchestrator-ledger.jsonl')


def append(ledger, **event):
    """Append one event as a JSON line."""
    ledger = Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    event['at'] = time.time()
    with ledger.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event) + '\n')


def replay(ledger):
    """Return ({ticket: {agent: info}}, {ticket: reason}, {done agent ids}) from the ledger."""
    assigned, reasons, done = {}, {}, set()
    ledger = Path(ledger)
    if not ledger.exists():
        return assigned, reasons, done
    for number, line in enumerate(ledger.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            op = event['op']
            agent = event['agent'] if op in {'assign', 'done'} else None
            text = event['text'] if op == 'reason' else None
        except (ValueError, KeyError, TypeError) as exc:
            print(f'{ledger}:{number} skipped, not a usable ledger event ({type(exc).__name__}: {exc})', file=sys.stderr)
            continue
        ticket = event.get('ticket')
        if op == 'assign':
            assigned.setdefault(ticket, {})[agent] = {'lane': event.get('lane'), 'role': event.get('role')}
            reasons.pop(ticket, None)
            done.discard(agent)
        elif op == 'done':
            done.add(agent)
        elif op == 'reason':
            reasons[ticket] = text
        elif op == 'clear':
            reasons.pop(ticket, None)
    return assigned, reasons, done


def find_transcript(agent, root=CLAUDE_PROJECT):
    """The subagent transcript `<root>/<session>/subagents/agent-<id>.jsonl`, or None."""
    name = agent if agent.startswith('agent-') else f'agent-{agent}'
    matches = list(Path(root).glob(f'*/subagents/{name}.jsonl'))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def liveness(agent, done, stale_minutes, now, root=CLAUDE_PROJECT):
    """'yes', 'no' or '?' (transcript not found, so assumed live)."""
    if agent in done:
        return 'no'
    transcript = find_transcript(agent, root)
    if transcript is None:
        return '?'
    return 'yes' if now - transcript.stat().st_mtime <= stale_minutes * 60 else 'no'


def analyse(tickets, assigned, reasons, done, stale=20, min_agents=8, now=None, root=CLAUDE_PROJECT):
    """Return the gap list and the live agent count.

    tickets: dicts with identifier, state (name), group, priority, name.
    """
    now = time.time() if now is None else now
    status = {}
    for agents in assigned.values():
        for agent in agents:
            status.setdefault(agent, liveness(agent, done, stale, now, root))
    live_agents = {a for a, s in status.items() if s != 'no'}
    gaps, unattended = [], False
    for ticket in tickets:
        if ticket['group'] in FINISHED_GROUPS:
            continue
        ident = ticket['identifier']
        agents = [a for a in assigned.get(ident, {}) if status[a] != 'no']
        if agents:
            continue
        if ticket['state'] == 'In Progress':
            # A recorded reason explains a wait, not In Progress: the state means an agent works on it.
            if reasons.get(ident, '').lower().startswith('waiting on donald'):
                kind = 'In Progress waiting on Donald: move to Backlog'
            else:
                kind = 'In Progress with no live agent: move to Queue, or Backlog if it waits on Donald'
        elif ident in reasons:
            continue
        elif ticket['state'] == 'Queue':
            kind = 'no agent and no reason'
        elif ticket['state'] == 'Backlog' and ticket['priority'] in WATCHED_BACKLOG:
            kind = 'backlog with no reason'
        else:
            continue
        unattended = True
        gaps.append({'kind': kind, 'ticket': ident, 'state': ticket['state'], 'priority': ticket['priority'],
                     'title': ticket['name']})
    result = {'gaps': gaps, 'live_agents': len(live_agents),
              'unknown_agents': sorted(a for a, s in status.items() if s == '?'),
              'below_minimum': bool(unattended and len(live_agents) < min_agents), 'min_agents': min_agents}
    return result


def load_tickets(client=None):
    """Read every ticket once and the state names once; reads only."""
    if client is None:
        from tools.plane.client import Client
        client = Client.load()
    states = {s['id']: s for s in client.metadata()['states']}
    rows = []
    for record in client.list():
        state = states.get(record['state'], {})
        rows.append({'identifier': record['identifier'], 'name': record['name'], 'priority': record['priority'],
                     'state': state.get('name', record['state']), 'group': state.get('group')})
    return rows


def render(result, titles=False):
    lines = []
    for gap in result['gaps']:
        line = f"{gap['ticket']} {gap['state']} {gap['priority']}: {gap['kind']}"
        lines.append(f"{line} ({gap['title']})" if titles else line)
    if result['below_minimum']:
        unknown = f", {len(result['unknown_agents'])} unconfirmed (?)" if result['unknown_agents'] else ''
        lines.append(f"{result['live_agents']} live agents, below {result['min_agents']}{unknown}")
    return lines or ['No gaps.']


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', type=Path, default=None)
    p.add_argument('--stale', type=float, default=20, metavar='MINUTES')
    p.add_argument('--min-agents', type=int, default=8)
    p.add_argument('--titles', action='store_true')
    p.add_argument('--json', action='store_true')
    sub = p.add_subparsers(dest='command')
    a = sub.add_parser('assign', help='Record an agent working on a ticket.')
    a.add_argument('ticket')
    a.add_argument('--agent', required=True)
    a.add_argument('--lane')
    a.add_argument('--role')
    sub.add_parser('done', help='Record that an agent finished.').add_argument('agent')
    r = sub.add_parser('reason', help='Record why nothing runs for a ticket.')
    r.add_argument('ticket')
    r.add_argument('text')
    sub.add_parser('clear', help='Drop the recorded reason for a ticket.').add_argument('ticket')
    return p


def main(argv=None, tickets=None, root=CLAUDE_PROJECT, now=None):
    args = parser().parse_args(argv)
    ledger = args.ledger or default_ledger()
    if args.command == 'assign':
        append(ledger, op='assign', ticket=args.ticket, agent=args.agent, lane=args.lane, role=args.role)
    elif args.command == 'done':
        append(ledger, op='done', agent=args.agent)
    elif args.command == 'reason':
        append(ledger, op='reason', ticket=args.ticket, text=args.text)
    elif args.command == 'clear':
        append(ledger, op='clear', ticket=args.ticket)
    else:
        from tools.plane.policy import PlaneError
        try:
            rows = load_tickets() if tickets is None else tickets
            result = analyse(rows, *replay(ledger), stale=args.stale, min_agents=args.min_agents, now=now, root=root)
        except (PlaneError, OSError, ValueError, KeyError) as exc:
            print(f'Queue gap check failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
        if args.json and not args.titles:
            result['gaps'] = [{k: v for k, v in gap.items() if k != 'title'} for gap in result['gaps']]
        print(json.dumps(result, indent=2) if args.json else '\n'.join(render(result, args.titles)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
