# Deploying fantasy-pl-mcp on Render

## Quick start

1. **Create a new Web Service** on [render.com](https://render.com) and connect this repo (`idlirshkurti/fantasy-pl-mcp`).
2. **Configure the service**:
   - **Branch**: `main`
   - **Root Directory**: (leave blank)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
   - **Environment**: Choose **Docker** if you want to use the Dockerfile, or **Python** for buildpack.
3. **Add environment variables** (optional, for authenticated FPL features):
   - `FPL_EMAIL` — your FPL login email
   - `FPL_PASSWORD` — your FPL password
   - `FPL_TEAM_ID` — your FPL team ID (optional)
4. **Deploy**. Render will give you a URL like `https://fpl-mcp.onrender.com`.

## Register as a custom connector

### Perplexity

1. Go to **Settings → Connectors → + Custom connector → Remote**.
2. Fill in:
   - **Name**: `Fantasy PL`
   - **MCP Server URL**: `https://<your-render-app>.onrender.com/sse` (or `/mcp`)
   - **Transport**: `SSE` or `Streamable HTTP` (match your choice)
   - **Authentication**: `None` (or API Key / OAuth if you add it)
3. Save, then enable the connector for chats.

### Cursor Cloud Agents

1. Go to **cursor.com/agents**.
2. Click **+** left of the prompt bar → **Add files, skills, and MCP servers**.
3. Hover **MCP Servers** → **Add MCP** → **Custom HTTP server**.
4. Set:
   - **URL**: `https://<your-render-app>.onrender.com/sse` (or `/mcp`)
   - Complete auth if needed.
5. Save and use in your agents.

## Notes

- **Free tier sleep**: Render free web services sleep after ~15 minutes of inactivity. The first request after idle will have a 30–60s cold start.
- **Keep warm (optional)**: Use a free cron service (e.g., cron-job.org, UptimeRobot) to ping `https://<your-render-app>.onrender.com/health` every ~10 minutes to avoid cold starts.
- **Security**: This basic setup has no auth on the HTTP endpoints. For production, add an API key or OAuth and configure the connector accordingly.
