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
from mcp.server.fastmcp import Context, FastMCP

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


def _client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context["client"]


def _error(resp: httpx.Response) -> str:
    """Format an API error with status and body for debugging."""
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", resp.text)
    except Exception:
        msg = resp.text
    return f"API error {resp.status_code}: {msg}"


def _format_badges(badges: dict) -> list[str]:
    """Format badge data into readable lines."""
    lines = []

    # Security badges
    security = badges.get("security", [])
    if security:
        items = []
        for b in security:
            icon = "+" if b.get("level") == "good" else ("-" if b.get("level") == "warn" else "~")
            items.append(f"{icon} {b['label']}: {b['value']}")
        lines.append("\nSecurity:")
        lines.extend(f"  {i}" for i in items)

    # Activity badges
    activity = badges.get("activity", [])
    if activity:
        items = []
        for b in activity:
            icon = "+" if b.get("level") == "good" else ("-" if b.get("level") == "warn" else "~")
            items.append(f"{icon} {b['label']}: {b['value']}")
        lines.append("\nActivity:")
        lines.extend(f"  {i}" for i in items)

    # Popularity (raw numbers)
    pop = badges.get("popularity", {})
    if pop:
        parts = []
        if pop.get("stars"):
            parts.append(f"{pop['stars']:,} stars")
        if pop.get("forks"):
            parts.append(f"{pop['forks']:,} forks")
        if pop.get("watchers"):
            parts.append(f"{pop['watchers']:,} watchers")
        if parts:
            lines.append(f"\nPopularity: {', '.join(parts)}")

    # Provenance checks
    prov = badges.get("provenance", [])
    if prov:
        passes = []
        fails = []
        for b in prov:
            if b.get("type") == "bool":
                (passes if b.get("value") else fails).append(b["label"])
            else:
                passes.append(f"{b['label']}: {b['value']}")
        lines.append("\nProvenance:")
        for p in passes:
            lines.append(f"  + {p}")
        for f in fails:
            lines.append(f"  - {f}")

    return lines


def _format_install(install: dict) -> list[str]:
    """Format install data into readable lines for model consumption."""
    lines = []
    if not install:
        return lines

    lines.append("\nInstall Info:")

    # Package install commands
    pkg_types = install.get("package_types", [])
    pkg_ids = install.get("package_identifiers", [])
    if pkg_types and pkg_ids:
        for ptype, pid in zip(pkg_types, pkg_ids):
            if ptype == "npm":
                lines.append(f"  npm: npx -y {pid}")
            elif ptype == "pypi":
                lines.append(f"  pypi: uvx {pid}")
            elif ptype == "oci":
                lines.append(f"  docker: {pid}")
            else:
                lines.append(f"  {ptype}: {pid}")

    # Transport
    transports = install.get("transport_types", [])
    if transports:
        lines.append(f"  Transport: {', '.join(transports)}")

    # Version
    version = install.get("version")
    if version:
        lines.append(f"  Version: {version}")

    # Env vars
    env_vars = install.get("env_vars", [])
    if env_vars:
        required = [v for v in env_vars if v.get("is_required")]
        optional = [v for v in env_vars if not v.get("is_required")]
        secret_note = lambda v: " (secret)" if v.get("is_secret") else ""
        if required:
            lines.append("  Required env vars:")
            for v in required:
                lines.append(f"    {v['name']}{secret_note(v)}")
        if optional:
            lines.append("  Optional env vars:")
            for v in optional:
                lines.append(f"    {v['name']}{secret_note(v)}")

    # Repo
    repo = install.get("repo_url")
    if repo:
        lines.append(f"  Source: {repo}")

    return lines


def _format_server(server: dict, detail: bool = True) -> str:
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

    if detail:
        badges = server.get("badges", {})
        if badges:
            lines.extend(_format_badges(badges))

        install = server.get("install", {})
        if install:
            lines.extend(_format_install(install))

    return "\n".join(lines)


def _format_server_line(s: dict, show_scores: bool = False) -> str:
    """Format a single server as a one-line summary."""
    flags = s.get("flags", [])
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    verified = " [Verified]" if s.get("verified_publisher") else ""
    targets = s.get("targets", [])
    target_str = f" ({', '.join(targets)})" if targets else ""

    # Package type indicator (works with both flat search results and nested install)
    pkg_types = s.get("package_types") or (s.get("install") or {}).get("package_types", [])
    pkg_str = f" [pkg: {','.join(pkg_types)}]" if pkg_types else ""

    line = f"- {s['name']}: {s['trust_score']}/100 ({s['trust_label']}){verified}{flag_str}{target_str}{pkg_str}"

    if show_scores:
        scores = s.get("scores", {})
        if scores:
            parts = [f"P:{scores.get('provenance','?')}", f"M:{scores.get('maintenance','?')}",
                     f"Pop:{scores.get('popularity','?')}", f"Perm:{scores.get('permissions','?')}"]
            line += f"  [{'/'.join(parts)}]"

    return line


@mcp.tool()
async def check_server_trust(ctx: Context, name: str) -> str:
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
        return _error(resp)

    data = resp.json().get("data", {})
    return _format_server(data, detail=True)


@mcp.tool()
async def search_servers(ctx: Context, query: str, limit: int = 10) -> str:
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
        return _error(resp)

    body = resp.json()
    results = body.get("data", [])

    if not results:
        return f"No servers found matching '{query}'."

    lines = [f"Found {len(results)} server(s) matching '{query}':\n"]
    for s in results:
        lines.append(_format_server_line(s))

    return "\n".join(lines)


@mcp.tool()
async def list_servers(
    ctx: Context,
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
        return _error(resp)

    body = resp.json()
    results = body.get("data", [])
    meta = body.get("meta", {})
    total = meta.get("total", "?")

    if not results:
        return "No servers match the given filters."

    lines = [f"Showing {len(results)} of {total} servers:\n"]
    for s in results:
        lines.append(_format_server_line(s, show_scores=True))

    if meta.get("total") and meta["total"] > offset + limit:
        lines.append(f"\n(Use offset={offset + limit} to see more)")

    return "\n".join(lines)


@mcp.tool()
async def get_ecosystem_stats(ctx: Context) -> str:
    """Get aggregate statistics about the MCP server ecosystem.

    Returns total server count, average/median trust scores, score distribution
    by trust label, flag summary, and verified publisher count.
    """
    client = _client(ctx)
    resp = await client.get("/v1/stats")

    if resp.status_code != 200:
        return _error(resp)

    stats = resp.json().get("data", {})
    total = stats.get("total_servers", 0)

    lines = [
        "## MCP Ecosystem Statistics\n",
        f"Total Servers: {total:,}",
        f"Average Trust Score: {stats.get('average_score', '?')}/100",
        f"Median Trust Score: {stats.get('median_score', '?')}/100",
        f"Verified Publishers: {stats.get('verified_publishers', '?')}",
        "\nScore Distribution:",
    ]

    dist = stats.get("score_distribution", {})
    for label in ["High Trust", "Moderate Trust", "Low Trust", "Very Low Trust", "Unknown/Suspicious"]:
        count = dist.get(label, 0)
        if count:
            pct = f" ({count * 100 / total:.1f}%)" if total else ""
            lines.append(f"  {label}: {count:,}{pct}")

    flag_summary = stats.get("flag_summary", {})
    if flag_summary:
        lines.append("\nFlag Summary:")
        for flag, count in sorted(flag_summary.items(), key=lambda x: -x[1]):
            lines.append(f"  {flag}: {count:,}")

    return "\n".join(lines)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
