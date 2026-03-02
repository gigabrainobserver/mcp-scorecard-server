# MCP Scorecard Server

An MCP server that lets AI models check trust scores for MCP servers before connecting. Powered by the [MCP Scorecard](https://mcp-scorecard.ai) trust index.

## What it does

Provides 4 tools to any MCP-compatible AI model:

- **check_server_trust** — Look up trust score and safety details for a specific server
- **search_servers** — Find servers by keyword
- **list_servers** — Browse and filter the full index
- **get_ecosystem_stats** — Aggregate statistics about the MCP ecosystem

## Quick start

```bash
# Get an API key at https://mcp-scorecard.ai
export SCORECARD_API_KEY=mcs_your_key_here

# Run with uv
uvx mcp-scorecard-server

# Or install and run
uv pip install mcp-scorecard-server
mcp-scorecard-server
```

## Claude Code integration

Add to your Claude Code MCP config (`.claude/settings.json`):

```json
{
  "mcpServers": {
    "mcp-scorecard": {
      "command": "uvx",
      "args": ["mcp-scorecard-server"],
      "env": {
        "SCORECARD_API_KEY": "mcs_your_key_here"
      }
    }
  }
}
```

Then ask Claude: *"Check the trust score for io.github.firebase/firebase-mcp"*

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCORECARD_API_KEY` | Yes | — | Your API key |
| `SCORECARD_API_URL` | No | `https://api.mcp-scorecard.ai` | API base URL |

## License

MIT
