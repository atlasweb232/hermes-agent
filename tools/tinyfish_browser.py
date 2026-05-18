"""TinyFish Browser and Agent API tools for Hermes Agent."""

from __future__ import annotations

import json
import os
from typing import Any, Literal, cast

from tools.registry import registry


def _to_jsonable(value: Any) -> Any:
    """Convert TinyFish/Pydantic responses into plain JSON-safe objects."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _json(data: Any) -> str:
    return json.dumps(_to_jsonable(data), ensure_ascii=False)


def _check_requirements() -> bool:
    try:
        import tinyfish  # noqa: F401
    except Exception:
        return False
    return bool(os.getenv("TINYFISH_API_KEY"))


def _client(timeout: int | float = 600):
    from tinyfish import TinyFish

    return TinyFish(api_key=os.getenv("TINYFISH_API_KEY"), timeout=float(timeout))


def tinyfish_fetch(
    urls: list[str],
    format: str = "markdown",
    links: bool = False,
    image_links: bool = False,
    timeout: int = 120,
) -> str:
    """Fetch one or more URLs through TinyFish Browser Fetch API."""
    try:
        fetch_format = cast(Literal["markdown", "html", "json"], format)
        response = _client(timeout=timeout).fetch.get_contents(
            urls=urls,
            format=fetch_format,
            links=links,
            image_links=image_links,
        )
        return _json({"success": True, "response": response})
    except Exception as exc:
        return _json({"success": False, "error": str(exc), "type": type(exc).__name__})


def tinyfish_search(query: str, location: str | None = None, language: str | None = None, timeout: int = 120) -> str:
    """Run a TinyFish web search query."""
    try:
        response = _client(timeout=timeout).search.query(
            query=query,
            location=location,
            language=language,
        )
        return _json({"success": True, "response": response})
    except Exception as exc:
        return _json({"success": False, "error": str(exc), "type": type(exc).__name__})


def tinyfish_agent_run(goal: str, url: str, timeout: int = 600) -> str:
    """Run a synchronous TinyFish browser agent task."""
    try:
        response = _client(timeout=timeout).agent.run(goal=goal, url=url)
        return _json({"success": True, "response": response})
    except Exception as exc:
        return _json({"success": False, "error": str(exc), "type": type(exc).__name__})


def tinyfish_agent_queue(goal: str, url: str, timeout: int = 120) -> str:
    """Queue an asynchronous TinyFish browser agent task and return its run_id."""
    try:
        response = _client(timeout=timeout).agent.queue(goal=goal, url=url)
        return _json({"success": True, "response": response})
    except Exception as exc:
        return _json({"success": False, "error": str(exc), "type": type(exc).__name__})


def tinyfish_run_status(run_id: str, timeout: int = 120) -> str:
    """Retrieve status/result for a queued TinyFish agent run."""
    try:
        response = _client(timeout=timeout).runs.get(run_id)
        return _json({"success": True, "response": response})
    except Exception as exc:
        return _json({"success": False, "error": str(exc), "type": type(exc).__name__})


registry.register(
    name="tinyfish_fetch",
    toolset="tinyfish",
    schema={
        "name": "tinyfish_fetch",
        "description": "Fetch one or more URLs using TinyFish Browser Fetch API and return extracted content.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "HTTP/HTTPS URLs to fetch."},
                "format": {"type": "string", "enum": ["markdown", "html", "json"], "default": "markdown"},
                "links": {"type": "boolean", "default": False, "description": "Include extracted page links."},
                "image_links": {"type": "boolean", "default": False, "description": "Include extracted image links."},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["urls"],
        },
    },
    handler=lambda args, **kw: tinyfish_fetch(
        urls=args["urls"],
        format=args.get("format", "markdown"),
        links=args.get("links", False),
        image_links=args.get("image_links", False),
        timeout=args.get("timeout", 120),
    ),
    check_fn=_check_requirements,
    requires_env=["TINYFISH_API_KEY"],
)

registry.register(
    name="tinyfish_search",
    toolset="tinyfish",
    schema={
        "name": "tinyfish_search",
        "description": "Search the web using TinyFish Search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "location": {"type": "string", "description": "Optional search location."},
                "language": {"type": "string", "description": "Optional language code."},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["query"],
        },
    },
    handler=lambda args, **kw: tinyfish_search(
        query=args["query"],
        location=args.get("location"),
        language=args.get("language"),
        timeout=args.get("timeout", 120),
    ),
    check_fn=_check_requirements,
    requires_env=["TINYFISH_API_KEY"],
)

registry.register(
    name="tinyfish_agent_run",
    toolset="tinyfish",
    schema={
        "name": "tinyfish_agent_run",
        "description": "Run a synchronous TinyFish browser agent task against a URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Natural language browser automation goal."},
                "url": {"type": "string", "description": "Starting URL for the browser agent."},
                "timeout": {"type": "integer", "default": 600},
            },
            "required": ["goal", "url"],
        },
    },
    handler=lambda args, **kw: tinyfish_agent_run(goal=args["goal"], url=args["url"], timeout=args.get("timeout", 600)),
    check_fn=_check_requirements,
    requires_env=["TINYFISH_API_KEY"],
)

registry.register(
    name="tinyfish_agent_queue",
    toolset="tinyfish",
    schema={
        "name": "tinyfish_agent_queue",
        "description": "Queue an asynchronous TinyFish browser agent task and return its run_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Natural language browser automation goal."},
                "url": {"type": "string", "description": "Starting URL for the browser agent."},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["goal", "url"],
        },
    },
    handler=lambda args, **kw: tinyfish_agent_queue(goal=args["goal"], url=args["url"], timeout=args.get("timeout", 120)),
    check_fn=_check_requirements,
    requires_env=["TINYFISH_API_KEY"],
)

registry.register(
    name="tinyfish_run_status",
    toolset="tinyfish",
    schema={
        "name": "tinyfish_run_status",
        "description": "Get status/result for a queued TinyFish browser agent run.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "TinyFish run_id returned by tinyfish_agent_queue."},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["run_id"],
        },
    },
    handler=lambda args, **kw: tinyfish_run_status(run_id=args["run_id"], timeout=args.get("timeout", 120)),
    check_fn=_check_requirements,
    requires_env=["TINYFISH_API_KEY"],
)
