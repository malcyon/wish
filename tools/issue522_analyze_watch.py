"""Summarise the logs `tools/issue522_probe_watch.py` writes.

Reads every worker's log under a run directory, merges the CREATE/DELETE
events for the two probe files that
`tests/test_conftest_state_guard.py::_run_throwaway_test` writes, and reports
whether the two probes' lifetimes overlapped and for how long.

Usage: `issue522_analyze_watch.py work/issue522/watch/run1 work/issue522/watch/run2 ...`
"""

from __future__ import annotations

import sys
from pathlib import Path


def events_for_run(run_dir: Path):
    events = {}  # name -> {"create": t, "delete": t}
    for log in run_dir.glob("*.log"):
        for line in log.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            ts, _worker, kind, name = parts
            if kind not in ("CREATE", "DELETE"):
                continue
            ts = float(ts)
            rec = events.setdefault(name, {})
            if kind == "CREATE":
                rec["create"] = min(rec.get("create", ts), ts)
            else:
                rec["delete"] = max(rec.get("delete", ts), ts)
    return events


def main(argv):
    overlap_count = 0
    total = 0
    for arg in argv:
        run_dir = Path(arg)
        events = events_for_run(run_dir)
        names = list(events)
        if len(names) != 2:
            print(f"{run_dir}: expected 2 probes, saw {len(names)}: {names}")
            continue
        total += 1
        a, b = names
        ca, da = events[a].get("create"), events[a].get("delete")
        cb, db = events[b].get("create"), events[b].get("delete")
        if None in (ca, da, cb, db):
            print(f"{run_dir}: incomplete lifetime a={events[a]} b={events[b]}")
            continue
        overlap_start = max(ca, cb)
        overlap_end = min(da, db)
        overlap = overlap_end - overlap_start
        if overlap > 0:
            overlap_count += 1
            print(f"{run_dir}: OVERLAP {overlap * 1000:.1f}ms "
                  f"(a alive {(da - ca) * 1000:.1f}ms, b alive {(db - cb) * 1000:.1f}ms)")
        else:
            print(f"{run_dir}: no overlap (gap {-overlap * 1000:.1f}ms)")
    print(f"\n{overlap_count} of {total} runs had overlapping probe lifetimes")


if __name__ == "__main__":
    main(sys.argv[1:])
