# plane

Apply Wish ticket policy to a single private Plane project.

| file | purpose |
|---|---|
| `__init__.py` | Marks the private ticket integration package. |
| `client.py` | Wraps the pinned vendor transport with project restrictions, pagination and filtered readback. |
| `mcp.py` | Registers only policy-filtered tools over local MCP stdio. |
| `migrate.py` | Transfers private source history into an explicitly selected rehearsal project with a provenance ledger. |
| `planeagent.py` | Creates, comments and changes tickets using stable operation IDs. |
| `planeread.py` | Lists, searches, reads and cites tickets through the policy layer. |
| `policy.py` | Validates configuration, filters authorship and protects writes with a durable journal. |
