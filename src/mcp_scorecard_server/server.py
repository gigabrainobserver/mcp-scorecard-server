"""MCP Scorecard server — lets AI models query trust scores for MCP servers.

Thin wrapper over the MCP Scorecard API at api.mcp-scorecard.ai.
Uses stdio transport for maximum safety scoring.

Env vars:
    SCORECARD_API_KEY  — required, your API key
    SCORECARD_API_URL  — optional, defaults to https://api.mcp-scorecard.ai
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_API_URL = "https://api.mcp-scorecard.ai"


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    api_key = os.environ.get("SCORECARD_API_KEY")
    if not api_key:
        raise ValueError("SCORECARD_API_KEY env var required")

    api_url = os.environ.get("SCORECARD_API_URL", DEFAULT_API_URL).rstrip("/")

    async with httpx.AsyncClient(
        base_url=api_url,
        headers={"X-API-Key": api_key},
        timeout=30.0,
    ) as client:
        yield {"client": client}


mcp = FastMCP("mcp-scorecard", lifespan=lifespan)


def _client(ctx) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context["client"]


def _format_server(server: dict) -> str:
    """Format a single server result for readable output."""
    scores = server.get("scores", {})
    flags = server.get("flags", [])
    targets = server.get("targets", [])

    lines = [
        f"## {server['name']}",
        f"Trust Score: {server['trust_score']}/100 ({server['trust_label']})",
        "",
        "Category Scores:",
        f"  Provenance:  {scores.get('provenance', '?')}/100",
        f"  Maintenance: {scores.get('maintenance', '?')}/100",
        f"  Popularity:  {scores.get('popularity', '?')}/100",
        f"  Permissions: {scores.get('permissions', '?')}/100",
    ]

    if server.get("verified_publisher"):
        lines.append("\nVerified Publisher: Yes")

    if flags:
        lines.append(f"\nFlags: {', '.join(flags)}")

    if targets:
        lines.append(f"Targets: {', '.join(targets)}")

    return "\n".join(lines)


@mcp.tool()
async def check_server_trust(ctx, name: str) -> str:
    """Check the trust score and safety details for a specific MCP server.

    Use this to evaluate whether an MCP server is safe to connect to.
    Returns trust score (0-100), category breakdowns, flags, and badges.

    Args:
        name: Full server name (e.g. "io.github.firebase/firebase-mcp")
    """
    client = _client(ctx)
    resp = await client.get(f"/v1/servers/{name}")

    if resp.status_code == 404:
        return f"Server '{name}' not found. Try search_servers to find it by keyword."
    if resp.status_code != 200:
        return f"API error: {resp.status_code}"

    data = resp.json().get("data", {})
    return _format_server(data)


@mcp.tool()
async def search_servers(ctx, query: str, limit: int = 10) -> str:
    """Search for MCP servers by name keyword.

    Use this when you don't know the exact server name. Returns matching
    servers sorted by trust score.

    Args:
        query: Search keyword (min 2 chars, e.g. "postgres", "firebase", "slack")
        limit: Max results to return (1-50, default 10)
    """
    limit = max(1, min(limit, 50))
    client = _client(ctx)
    resp = await client.get("/v1/search", params={"q": query, "limit": limit})

    if resp.status_code != 200:
        return f"API error: {resp.status_code}"

    body = resp.json()
    results = body.get("data", [])

    if not results:
        return f"No servers found matching '{query}'."

    lines = [f"Found {len(results)} server(s) matching '{query}':\n"]
    for s in results:
        flags = s.get("flags", [])
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        verified = " [Verified]" if s.get("verified_publisher") else ""
        lines.append(
            f"- {s['name']}: {s['trust_score']}/100 ({s['trust_label']}){verified}{flag_str}"
        )

    return "\n".join(lines)


@mcp.tool()
async def list_servers(
    ctx,
    min_score: int | None = None,
    flags: str | None = None,
    target: str | None = None,
    namespace: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "trust_score",
    order: str = "desc",
) -> str:
    """Browse and filter MCP servers from the trust index.

    Use this to explore the ecosystem — find high-trust servers, filter by
    platform target, or identify servers with specific flags.

    Args:
        min_score: Minimum trust score (0-100)
        flags: Filter by flag (e.g. "SENSITIVE_CRED_REQUEST", "NO_SOURCE")
        target: Filter by platform (e.g. "PostgreSQL", "Slack", "Firebase")
        namespace: Filter by publisher namespace (e.g. "com.microsoft")
        limit: Results per page (1-50, default 20)
        offset: Pagination offset (default 0)
        sort: Sort field (trust_score, name, provenance, maintenance, popularity, permissions)
        order: Sort direction (asc or desc)
    """
    limit = max(1, min(limit, 50))
    params: dict = {"limit": limit, "offset": offset, "sort": sort, "order": order}
    if min_score is not None:
        params["min_score"] = min_score
    if flags:
        params["flags"] = flags
    if target:
        params["target"] = target
    if namespace:
        params["namespace"] = namespace

    client = _client(ctx)
    resp = await client.get("/v1/servers", params=params)

    if resp.status_code != 200:
        return f"API error: {resp.status_code}"

    body = resp.json()
    results = body.get("data", [])
    meta = body.get("meta", {})
    total = meta.get("total", "?")

    if not results:
        return "No servers match the given filters."

    lines = [f"Showing {len(results)} of {total} servers:\n"]
    for s in results:
        flag_str = f" [{', '.join(s.get('flags', []))}]" if s.get("flags") else ""
        verified = " [Verified]" if s.get("verified_publisher") else ""
        lines.append(
            f"- {s['name']}: {s['trust_score']}/100 ({s['trust_label']}){verified}{flag_str}"
        )

    if meta.get("total") and meta["total"] > offset + limit:
        lines.append(f"\n(Use offset={offset + limit} to see more)")

    return "\n".join(lines)


@mcp.tool()
async def get_ecosystem_stats(ctx) -> str:
    """Get aggregate statistics about the MCP server ecosystem.

    Returns total server count, average/median trust scores, score distribution
    by trust label, flag summary, and verified publisher count.
    """
    client = _client(ctx)
    resp = await client.get("/v1/stats")

    if resp.status_code != 200:
        return f"API error: {resp.status_code}"

    stats = resp.json().get("data", {})

    lines = [
        "## MCP Ecosystem Statistics\n",
        f"Total Servers: {stats.get('total_servers', '?')}",
        f"Average Trust Score: {stats.get('average_score', '?')}/100",
        f"Median Trust Score: {stats.get('median_score', '?')}/100",
        f"Verified Publishers: {stats.get('verified_publishers', '?')}",
        "\nScore Distribution:",
    ]

    dist = stats.get("score_distribution", {})
    for label in ["High Trust", "Moderate Trust", "Low Trust", "Very Low Trust", "Unknown/Suspicious"]:
        count = dist.get(label, 0)
        if count:
            lines.append(f"  {label}: {count}")

    flag_summary = stats.get("flag_summary", {})
    if flag_summary:
        lines.append("\nFlag Summary:")
        for flag, count in sorted(flag_summary.items(), key=lambda x: -x[1]):
            lines.append(f"  {flag}: {count}")

    return "\n".join(lines)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
