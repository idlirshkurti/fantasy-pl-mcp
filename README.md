# Fantasy Premier League MCP Gateway

A hosted **Model Context Protocol (MCP) gateway** for Fantasy Premier League (FPL) data, deployed as a remote HTTP API. This repository is a fork of [rishijatia/fantasy-pl-mcp](https://github.com/rishijatia/fantasy-pl-mcp), which is a local, stdio-based MCP server for Claude Desktop. **This fork changes the delivery model**: instead of spawning `fpl_mcp` directly inside a desktop client, it wraps that same package behind a FastAPI gateway (`server.py`) that any MCP-compatible client can reach over plain HTTPS, with bearer-token authentication and Render-based deployment.

If you want the original local/stdio server for Claude Desktop, use the upstream project directly. Use this fork if you want to run FPL tools as a shared, remotely-hosted MCP endpoint (e.g. for the Perplexity MCP connector, a team-shared Claude/Cursor setup, or any other Streamable-HTTP MCP client).

## Architecture

```
MCP client (Perplexity, Claude, Cursor, ...)
        │  HTTPS, Bearer <MCP_API_TOKEN>
        ▼
   FastAPI gateway (server.py)
        │
        ├─ get_team / get_my_team / get_my_current_team
        │      → served directly from the public FPL API
        │        (https://fantasy.premierleague.com/api/entry/{id}/event/{gw}/picks/)
        │
        └─ everything else (analyze_players, compare_players,
           get_gameweek_status, resources, prompts, ...)
               → proxied over stdio to a managed `python -m fpl_mcp`
                 subprocess (the unmodified upstream package)
```

The gateway does two things the upstream package doesn't:

1. **Remote HTTP transport** — exposes a single `POST /mcp` JSON-RPC 2.0 endpoint and a `GET /health` liveness check, instead of requiring a local process spawn.
2. **Safety controls** — enforces a bearer token on every `/mcp` request, blocks the `update_fpl_credentials` tool from being called remotely, and (for the intercepted team-lookup tools) logs only non-sensitive diagnostics — upstream FPL HTTP status, numeric team ID, and resolved gameweek — on failure, never credentials, tokens, headers, or response bodies.

## Deployment

This service is deployed on [Render](https://render.com) via Docker. See [`render.md`](./render.md) and the [`Dockerfile`](./Dockerfile) for the full deployment configuration, including PR-preview environments that let you validate changes on a live URL before merging.

### Required environment variables

| Variable | Purpose |
|---|---|
| `MCP_API_TOKEN` | Bearer token required on every `POST /mcp` request to this gateway. |
| `FPL_TEAM_ID` | Default team ID used by `get_my_team` / `get_my_current_team`. |
| `FPL_EMAIL` / `FPL_PASSWORD` (or refresh token, per upstream auth flow) | Credentials the underlying `fpl_mcp` subprocess uses for tools that need authenticated FPL access (e.g. `get_manager_info`). Not required for the public team-lookup tools. |
| `PORT` | Port the gateway listens on (defaults to `8000`; Render sets this automatically). |

### Running locally

```bash
pip install -r requirements.txt
export MCP_API_TOKEN=some-local-secret
python server.py
```

Then call it like any HTTP MCP server:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer some-local-secret" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Endpoints

- `GET /health` — liveness probe, returns `{"status": "ok"}`. No authentication required.
- `POST /mcp` — the MCP JSON-RPC 2.0 endpoint. Requires `Authorization: Bearer <MCP_API_TOKEN>`. Supports `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, and (via subprocess proxy) `resources/list`, `resources/read`, `prompts/list`, `prompts/get`.

## Authentication model

There are two independent layers of authentication, and they're easy to conflate:

1. **Gateway auth** — the `Authorization: Bearer <MCP_API_TOKEN>` header required to reach this service at all. Set by you, checked on every `/mcp` request.
2. **FPL account auth** — the `FPL_EMAIL`/`FPL_PASSWORD` (or refresh token) credentials the *underlying* `fpl_mcp` package uses to call authenticated FPL endpoints (e.g. `get_manager_info`). These live on the server, never in the request, and the `update_fpl_credentials` tool that would normally let a client update them remotely is explicitly **blocked** by this gateway — it must be changed by editing server environment variables directly, not via any MCP client.

The three team-lookup tools (`get_team`, `get_my_team`, `get_my_current_team`) bypass the `fpl_mcp` subprocess entirely and call FPL's public `/api/entry/{id}/event/{gw}/picks/` endpoint directly, since that data doesn't require FPL account authentication.

## Available tools

These come from the unmodified upstream `fpl_mcp` package; everything except the first three is proxied through as-is.

**Intercepted by the gateway (served from the public FPL API directly):**
- `get_team` — view any team by ID.
- `get_my_team` — view your own team (uses `FPL_TEAM_ID`).
- `get_my_current_team` — view your own team for the current gameweek.

**Proxied to the `fpl_mcp` subprocess:**
- `get_gameweek_status` — current, previous, and next gameweek info.
- `analyze_player_fixtures` — fixture difficulty for a specific player.
- `get_blank_gameweeks` / `get_double_gameweeks` — upcoming blank/double gameweeks.
- `analyze_players` — filter/analyze players by multiple criteria.
- `analyze_fixtures` — fixture difficulty for players, teams, or positions.
- `compare_players` — compare multiple players across metrics.
- `check_fpl_authentication` — verify the server's FPL credentials work.
- `get_manager_info` — manager details (requires FPL account auth).

## Available resources & prompt templates

Also proxied through unchanged from `fpl_mcp`:

**Resources:** `fpl://static/players`, `fpl://static/players/{name}`, `fpl://static/teams`, `fpl://static/teams/{name}`, `fpl://gameweeks/current`, `fpl://gameweeks/all`, `fpl://fixtures`, `fpl://fixtures/gameweek/{gameweek_id}`, `fpl://fixtures/team/{team_name}`, `fpl://players/{player_name}/fixtures`, `fpl://gameweeks/blank`, `fpl://gameweeks/double`.

**Prompt templates:** `player_analysis_prompt`, `transfer_advice_prompt`, `team_rating_prompt`, `differential_players_prompt`, `chip_strategy_prompt`.

## Security notes

- Every `/mcp` request must present a valid bearer token; requests without one get a `401` with a `WWW-Authenticate: Bearer` header.
- `update_fpl_credentials` is never reachable through this gateway, in `tools/list` or `tools/call`, regardless of caller.
- Diagnostic logging for failed public team lookups is limited to the upstream FPL HTTP status code, the numeric team ID, and the resolved gameweek — never `MCP_API_TOKEN`, `FPL_EMAIL`, `FPL_PASSWORD`, refresh/access tokens, authorization headers, request bodies, or FPL response bodies.
- The `fpl_mcp` subprocess is managed through the FastAPI app lifespan: it's started once at boot, its stderr is drained and logged, and it's terminated (with a kill fallback) on shutdown.

## Limitations

- The FPL API is not officially documented and may change without notice.
- Only read operations are currently supported.
- Public team-lookup tools depend on FPL having published picks for the requested gameweek — during preseason or before a gameweek's deadline, every team lookup will correctly 404 because no picks exist yet, not because of a bug in this gateway.

## Local/legacy usage (Claude Desktop, stdio)

The underlying `fpl_mcp` package can still be run locally exactly as documented upstream, independent of this gateway, if you want a desktop-only setup:

```bash
pip install fpl-mcp
python -m fpl_mcp
```

See [rishijatia/fantasy-pl-mcp](https://github.com/rishijatia/fantasy-pl-mcp) for the full local installation, Claude Desktop configuration, and troubleshooting guide for that mode.

## Contributing

Contributions are welcome — please see [`CONTRIBUTING.md`](./CONTRIBUTING.md). Changes to `server.py` should go through a feature branch and pull request, validated against a Render PR-preview deployment before merging.

## License

This project is licensed under the MIT License — see the [`LICENSE`](./LICENSE) file for details.

## Acknowledgments

- [rishijatia/fantasy-pl-mcp](https://github.com/rishijatia/fantasy-pl-mcp) for the original FPL MCP server and all of its tools, resources, and prompt templates, which this gateway wraps unmodified.
- Fantasy Premier League API for providing the underlying data.
- Model Context Protocol for the connectivity standard.
