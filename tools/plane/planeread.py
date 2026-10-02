#!/usr/bin/env python3
"""Read or cite Plane tickets through Wish's filtering policy."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.plane.client import Client
from tools.plane.policy import PlaneError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('identifier', nargs='?')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--search')
    parser.add_argument('--cite', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--metadata', action='store_true')
    args = parser.parse_args(argv)
    try:
        client = Client.load()
        if args.metadata:
            result = client.metadata()
        elif args.list or args.search is not None:
            result = client.list(args.search)
        elif args.identifier:
            result = client.read(args.identifier)
            if args.cite:
                print(client.policy.citation(result))
                return 0
        else:
            parser.error('An identifier, --list, --search or --metadata is required')
        print(json.dumps(result, indent=2))
        return 0
    except (PlaneError, OSError, ValueError, KeyError) as exc:
        print(f'Plane read failed: {type(exc).__name__}' if not isinstance(exc, PlaneError) else str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
