"""
MCP-style and direct API clients for external tools.

Supported integrations:
- BigQuery
- Google Maps
- Google Calendar
- Google Tasks

When live endpoints or access tokens are unset, deterministic mocks keep the
stack runnable for demos and local development.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


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

CALENDAR_LIST_EVENTS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "time_min": {"type": "string", "description": "ISO-8601 inclusive start"},
        "time_max": {"type": "string", "description": "ISO-8601 exclusive end"},
        "max_results": {"type": "integer", "default": 20},
    },
    "required": ["time_min", "time_max"],
}

CALENDAR_CREATE_EVENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "start_iso": {"type": "string"},
        "end_iso": {"type": "string"},
        "location": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "start_iso", "end_iso"],
}

TASKS_LIST_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "show_completed": {"type": "boolean", "default": False},
        "max_results": {"type": "integer", "default": 20},
    },
}

TASKS_CREATE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "notes": {"type": "string"},
        "due_iso": {"type": "string"},
        "status": {"type": "string", "enum": ["needsAction", "completed"], "default": "needsAction"},
    },
    "required": ["title"],
}


class BaseMCPClient(ABC):
    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class MockBigQueryMCP(BaseMCPClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "run_query":
            return {"error": f"unknown tool {name}"}
        q = (arguments.get("query") or "").lower()
        if "revenue" in q or "sales" in q:
            rows = [
                {"region": "US", "revenue_usd": 125000, "period": "2026-Q1"},
                {"region": "EU", "revenue_usd": 98000, "period": "2026-Q1"},
            ]
        else:
            rows = [{"message": "mock result — configure real BigQuery MCP for production data"}]
        return {"rows": rows, "stats": {"mock": True, "bytes_processed": 0}}


class MockMapsMCP(BaseMCPClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "compute_route":
            return {"error": f"unknown tool {name}"}
        origin = arguments.get("origin", "")
        destination = arguments.get("destination", "")
        mode = arguments.get("mode", "driving")
        base = 600 + min(2400, len(origin) * 3 + len(destination) * 3)
        if mode == "walking":
            base *= 4
        return {
            "duration_seconds": float(base),
            "distance_meters": float(base * 1.2),
            "summary": f"{mode} from {origin!r} to {destination!r} (mock)",
        }


class MockCalendarMCP(BaseMCPClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_events":
            start = arguments.get("time_min") or f"{datetime.utcnow().date().isoformat()}T09:00:00"
            end = arguments.get("time_max") or f"{datetime.utcnow().date().isoformat()}T17:00:00"
            return {
                "events": [
                    {
                        "id": "mock-gcal-1",
                        "title": "Product sync",
                        "start_at": start,
                        "end_at": min(end, start[:11] + "09:30:00"),
                        "location": "Google Meet",
                        "source": "google_calendar_mock",
                    }
                ],
                "stats": {"mock": True},
            }
        if name == "create_event":
            return {
                "status": "created",
                "id": "mock-created-event",
                "html_link": "https://calendar.google.com/calendar/u/0/r",
                "source": "google_calendar_mock",
            }
        return {"error": f"unknown tool {name}"}


class MockTasksMCP(BaseMCPClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_tasks":
            return {
                "tasks": [
                    {
                        "id": "mock-task-1",
                        "title": "Follow up on quarterly roadmap",
                        "status": "needsAction",
                        "due_at": None,
                        "source": "google_tasks_mock",
                    }
                ],
                "stats": {"mock": True},
            }
        if name == "create_task":
            return {"status": "created", "id": "mock-created-task", "source": "google_tasks_mock"}
        return {"error": f"unknown tool {name}"}


class HttpSSEMCPClient(BaseMCPClient):
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self._base}/invoke", json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("result", data)


class GoogleCalendarRESTClient(BaseMCPClient):
    def __init__(self, access_token: str, calendar_id: str):
        self._access_token = access_token
        self._calendar_id = calendar_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        encoded_id = quote(self._calendar_id, safe="")
        base = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events"
        async with httpx.AsyncClient(timeout=60.0) as client:
            if name == "list_events":
                params = {
                    "timeMin": arguments["time_min"],
                    "timeMax": arguments["time_max"],
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": int(arguments.get("max_results", 20)),
                }
                r = await client.get(base, headers=self._headers(), params=params)
                r.raise_for_status()
                data = r.json()
                return {
                    "events": [
                        {
                            "id": item.get("id"),
                            "title": item.get("summary") or "Untitled",
                            "start_at": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date"),
                            "end_at": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date"),
                            "location": item.get("location"),
                            "html_link": item.get("htmlLink"),
                            "source": "google_calendar",
                        }
                        for item in data.get("items", [])
                    ],
                    "stats": {"calendar_id": self._calendar_id},
                }
            if name == "create_event":
                payload = {
                    "summary": arguments["title"],
                    "location": arguments.get("location"),
                    "description": arguments.get("description"),
                    "start": {"dateTime": arguments["start_iso"]},
                    "end": {"dateTime": arguments["end_iso"]},
                }
                r = await client.post(base, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)
                r.raise_for_status()
                data = r.json()
                return {
                    "status": "created",
                    "id": data.get("id"),
                    "html_link": data.get("htmlLink"),
                    "source": "google_calendar",
                }
        return {"error": f"unknown tool {name}"}


class GoogleTasksRESTClient(BaseMCPClient):
    def __init__(self, access_token: str, tasklist_id: str):
        self._access_token = access_token
        self._tasklist_id = tasklist_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        encoded_id = quote(self._tasklist_id, safe="")
        base = f"https://tasks.googleapis.com/tasks/v1/lists/{encoded_id}/tasks"
        async with httpx.AsyncClient(timeout=60.0) as client:
            if name == "list_tasks":
                params = {
                    "showCompleted": str(bool(arguments.get("show_completed", False))).lower(),
                    "showHidden": "false",
                    "maxResults": int(arguments.get("max_results", 20)),
                }
                r = await client.get(base, headers=self._headers(), params=params)
                r.raise_for_status()
                data = r.json()
                return {
                    "tasks": [
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "status": item.get("status"),
                            "due_at": item.get("due"),
                            "notes": item.get("notes"),
                            "source": "google_tasks",
                        }
                        for item in data.get("items", [])
                    ],
                    "stats": {"tasklist_id": self._tasklist_id},
                }
            if name == "create_task":
                payload = {
                    "title": arguments["title"],
                    "notes": arguments.get("notes"),
                    "status": arguments.get("status", "needsAction"),
                }
                if arguments.get("due_iso"):
                    payload["due"] = arguments["due_iso"]
                r = await client.post(base, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)
                r.raise_for_status()
                data = r.json()
                return {
                    "status": "created",
                    "id": data.get("id"),
                    "source": "google_tasks",
                }
        return {"error": f"unknown tool {name}"}


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


def get_calendar_client() -> BaseMCPClient:
    s = get_settings()
    if s.mcp_calendar_sse_url:
        return HttpSSEMCPClient(s.mcp_calendar_sse_url)
    if s.google_workspace_access_token:
        return GoogleCalendarRESTClient(s.google_workspace_access_token, s.google_calendar_id)
    return MockCalendarMCP()


def get_tasks_client() -> BaseMCPClient:
    s = get_settings()
    if s.mcp_tasks_sse_url:
        return HttpSSEMCPClient(s.mcp_tasks_sse_url)
    if s.google_workspace_access_token:
        return GoogleTasksRESTClient(s.google_workspace_access_token, s.google_tasks_list_id)
    return MockTasksMCP()


def schemas_bundle() -> str:
    return json.dumps(
        {
            "bigquery": {"input": BIGQUERY_RUN_QUERY_INPUT_SCHEMA, "output": BIGQUERY_RUN_QUERY_OUTPUT_SCHEMA},
            "maps": {"input": MAPS_ROUTE_INPUT_SCHEMA, "output": MAPS_ROUTE_OUTPUT_SCHEMA},
            "google_calendar": {
                "list_events_input": CALENDAR_LIST_EVENTS_INPUT_SCHEMA,
                "create_event_input": CALENDAR_CREATE_EVENT_INPUT_SCHEMA,
            },
            "google_tasks": {
                "list_tasks_input": TASKS_LIST_INPUT_SCHEMA,
                "create_task_input": TASKS_CREATE_INPUT_SCHEMA,
            },
        },
        indent=2,
    )
