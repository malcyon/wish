#!/usr/bin/env python3
"""Write Plane tickets as the dedicated agent."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.plane.client import CREATE_STATES, Client
from tools.plane.policy import PlaneError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--title', required=True)
    create.add_argument('--body-file', type=Path, required=True)
    create.add_argument('--priority', choices=['urgent', 'high', 'medium', 'low', 'none'], required=True)
    create.add_argument('--label', action='append', required=True)
    create.add_argument('--state', choices=CREATE_STATES, default='Backlog')
    comment = commands.add_parser('comment')
    comment.add_argument('identifier')
    comment.add_argument('--body-file', type=Path, required=True)
    edit = commands.add_parser('edit-comment')
    edit.add_argument('identifier')
    edit.add_argument('--comment-id', required=True)
    edit.add_argument('--body-file', type=Path, required=True)
    update = commands.add_parser('update')
    update.add_argument('identifier')
    update.add_argument('--changes-file', type=Path, required=True)
    update.add_argument('--explanation-file', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        client = Client.load()
        if args.command == 'create':
            extra = {} if args.state == 'Backlog' else {'state': args.state}
            result = client.create(args.title, args.body_file.read_text(), args.priority, args.label, **extra)
        elif args.command == 'comment':
            result = client.comment(args.identifier, args.body_file.read_text())
        elif args.command == 'edit-comment':
            result = client.edit_comment(args.identifier, args.comment_id, args.body_file.read_text())
        else:
            result = client.update(args.identifier, json.loads(args.changes_file.read_text()), args.explanation_file.read_text())
        print(json.dumps(result, indent=2))
        return 0
    except (PlaneError, OSError, ValueError, KeyError) as exc:
        print(f'Plane write failed: {type(exc).__name__}' if not isinstance(exc, PlaneError) else str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
