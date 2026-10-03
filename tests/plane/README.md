# Plane tests

These tests exercise private ticket filtering, write protection and migration evidence.

| File | Purpose |
|---|---|
| `conftest.py` | Restricts Linux migration storage checks to POSIX permissions while keeping portable policy checks enabled. |
| `test_policy.py` | Checks authorship, imported provenance, complete pagination and durable duplicate prevention. |
| `test_migrate.py` | Checks private migration records, provenance and ambiguous import protection. |
