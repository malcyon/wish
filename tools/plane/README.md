# Plane

Apply Wish ticket policy to a single private Plane project.

| File | Purpose |
|---|---|
| `__init__.py` | Marks the private ticket integration package. |
| `client.py` | Wraps the pinned vendor transport with project restrictions, pagination and full private readback. |
| `mcp.py` | Registers only project-scoped tools over local MCP stdio. |
| `planeagent.py` | Creates, comments and changes tickets using stable operation IDs. |
| `planeread.py` | Lists, searches, reads and cites tickets through the policy layer. |
| `policy.py` | Validates private project configuration and protects writes with a durable journal. |
