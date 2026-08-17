# Remote MCP gateway

Set `MCP_API_TOKEN` as a Render secret. The service refuses to start without it. Every `POST /mcp` request requires `Authorization: Bearer <MCP_API_TOKEN>`. Do not commit or log the token. `/health` remains public for Render.

`update_fpl_credentials` is deliberately unavailable through the remote gateway. Browser origin checks do not replace bearer authentication.
