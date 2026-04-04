"""
MCP-style clients for BigQuery and Google Maps.

Production: point `mcp_bigquery_sse_url` / `mcp_maps_sse_url` at your MCP servers
(SSE transport). When unset, `MockBigQueryMCP` / `MockMapsMCP` provide deterministic
fixtures so the stack runs without external MCP processes.

The official `mcp` PyPI package requires Python 3.10+; this module uses httpx + JSON
schemas so it works on 3.9+ and mirrors MCP tool input/output contracts.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# --- JSON Schemas (documentation + validation hints) ---

BIGQUERY_RUN_QUERY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Standard SQL (BigQuery dialect)"},
        "max_rows": {"type": "integer", "default": 100},
    },
    "required": ["query"],
}

BIGQUERY_RUN_QUERY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rows": {"type": "array", "items": {"type": "object"}},
        "stats": {"type": "object"},
    },
}

MAPS_ROUTE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "origin": {"type": "string"},
        "destination": {"type": "string"},
        "mode": {"type": "string", "enum": ["driving", "walking", "transit"], "default": "driving"},
        "departure_time": {"type": "string", "description": "ISO-8601 optional"},
    },
    "required": ["origin", "destination"],
}

MAPS_ROUTE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "duration_seconds": {"type": "number"},
        "distance_meters": {"type": "number"},
        "summary": {"type": "string"},
    },
}


class BaseMCPClient(ABC):
    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class MockBigQueryMCP(BaseMCPClient):
    """Returns sample rows for analytics-style questions (no network)."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "run_query":
            return {"error": f"unknown tool {name}"}
        q = (arguments.get("query") or "").lower()
        rows: list[dict[str, Any]]
        if "revenue" in q or "sales" in q:
            rows = [
                {"region": "US", "revenue_usd": 125000, "period": "2026-Q1"},
                {"region": "EU", "revenue_usd": 98000, "period": "2026-Q1"},
            ]
        else:
            rows = [{"message": "mock result — configure real BigQuery MCP for production data"}]
        return {"rows": rows, "stats": {"mock": True, "bytes_processed": 0}}


class MockMapsMCP(BaseMCPClient):
    """Heuristic travel times for scheduling (replace with Routes API via MCP)."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "compute_route":
            return {"error": f"unknown tool {name}"}
        origin = arguments.get("origin", "")
        destination = arguments.get("destination", "")
        mode = arguments.get("mode", "driving")
        # toy model: longer strings -> slightly longer trip
        base = 600 + min(2400, len(origin) * 3 + len(destination) * 3)
        if mode == "walking":
            base *= 4
        return {
            "duration_seconds": float(base),
            "distance_meters": float(base * 1.2),
            "summary": f"{mode} from {origin!r} to {destination!r} (mock)",
        }


class HttpSSEMCPClient(BaseMCPClient):
    """Minimal JSON-RPC-style caller for remote MCP HTTP gateways (adapter)."""

    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self._base}/invoke", json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("result", data)


def get_bigquery_mcp() -> BaseMCPClient:
    s = get_settings()
    if s.mcp_bigquery_sse_url:
        return HttpSSEMCPClient(s.mcp_bigquery_sse_url)
    return MockBigQueryMCP()


def get_maps_mcp() -> BaseMCPClient:
    s = get_settings()
    if s.mcp_maps_sse_url:
        return HttpSSEMCPClient(s.mcp_maps_sse_url)
    return MockMapsMCP()


def schemas_bundle() -> str:
    """Human-readable schema dump for orchestrator prompts."""
    return json.dumps(
        {
            "bigquery": {
                "input": BIGQUERY_RUN_QUERY_INPUT_SCHEMA,
                "output": BIGQUERY_RUN_QUERY_OUTPUT_SCHEMA,
            },
            "maps": {"input": MAPS_ROUTE_INPUT_SCHEMA, "output": MAPS_ROUTE_OUTPUT_SCHEMA},
        },
        indent=2,
    )
