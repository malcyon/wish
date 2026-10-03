# Plane tests

These tests exercise private ticket filtering, write protection and migration evidence.

| File | Purpose |
|---|---|
| `test_policy.py` | Checks authorship, imported provenance, complete pagination and durable duplicate prevention. |
| `test_migrate.py` | Checks private migration records, provenance and ambiguous import protection. |
| `test_attachments.py` | Checks streaming limits, credential confinement, interrupted uploads and remote byte verification. |
| `test_relations.py` | Checks dependency direction, conflicting links, missing targets and safe restart behavior. |
