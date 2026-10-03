# plane

Apply Wish ticket policy to a single private Plane project.

| file | purpose |
|---|---|
| `__init__.py` | Marks the private ticket integration package. |
| `attachments.py` | Streams source attachments privately and verifies uploaded bytes through a durable migration ledger. |
| `client.py` | Wraps the pinned vendor transport with project restrictions, pagination and filtered readback. |
| `mcp.py` | Registers only policy-filtered tools over local MCP stdio. |
| `migrate.py` | Imports private source history into separately authorized rehearsal or production projects with durable provenance. |
| `planeagent.py` | Creates, comments and changes tickets using stable operation IDs. |
| `planeread.py` | Lists, searches, reads and cites tickets through the policy layer. |
| `policy.py` | Validates configuration, filters authorship and protects writes with a durable journal. |
| `relations.py` | Imports native dependency direction and blocks incomplete or conflicting relation changes. |
