# Plane tools

These tools apply Wish policy before private Plane ticket text reaches an agent.

| File | Purpose |
|---|---|
| `__init__.py` | Marks the private ticket integration package. |
| `policy.py` | Validates configuration, filters authorship and protects writes with a durable journal. |
| `client.py` | Wraps the pinned vendor transport with project restrictions, pagination and filtered readback. |
| `planeread.py` | Lists, searches, reads and cites tickets through the policy layer. |
| `planeagent.py` | Creates, comments and changes tickets using stable operation IDs. |
| `mcp.py` | Registers only policy-filtered tools over local MCP stdio. |
| `migrate.py` | Transfers private source history into an explicitly selected rehearsal project with a provenance ledger. |
