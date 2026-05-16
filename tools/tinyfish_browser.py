"""TinyFish Browser API tool integration for Hermes Agent.

This tool provides a simple wrapper around the ``tinyfish`` library, exposing
a ``tinyfish_browser`` function that can be called by coding agents. The
function accepts a single URL and returns the JSON response from the TinyFish
API as a string. The tool is registered with the Hermes tool registry so
that it appears in the list of available tools when the appropriate
environment (Python with ``tinyfish`` installed) is present.
"""

import json
from typing import Any, Dict

# Import the tinyfish client – it is installed in the Hermes virtual
# environment (see the ``pip install tinyfish`` step performed earlier).
from tinyfish import TinyFish

# The registry singleton lives in ``hermes_agent.tools.registry``. Importing
# it lazily avoids circular imports when the tool file is imported during
# Hermes startup.
from hermes_agent.tools.registry import registry


def _check_requirements() -> bool:
    """Return True if the tinyfish package is importable.

    Hermes only shows tools whose ``check_fn`` returns ``True``. This guard
    ensures the tool disappears gracefully if the package is removed.
    """
    try:
        # The import already succeeded above, but we keep the guard for
        # environments where the file might be loaded before the package is
        # installed.
        import tinyfish  # noqa: F401
    except Exception:
        return False
    return True


def tinyfish_browser(url: str, timeout: int = 30) -> str:
    """Fetch the given URL using TinyFish and return the raw JSON body.

    Args:
        url: The target URL to request. Must be a fully qualified HTTP/HTTPS
            URL.
        timeout: Request timeout in seconds (default 30).

    Returns:
        A JSON‑encoded string containing the response data. If the request
        fails, the JSON includes an ``error`` field with details.
    """
    client = TinyFish()
    try:
        resp = client.get(url, timeout=timeout)
        # ``resp`` is a ``requests.Response``‑like object.
        data: Dict[str, Any] = {
            "status": resp.status_code,
            "url": resp.url,
            "headers": dict(resp.headers),
            "content": resp.json() if "application/json" in resp.headers.get("Content-Type", "") else resp.text,
        }
    except Exception as exc:
        data = {"error": str(exc)}
    return json.dumps(data)

# Register the tool with Hermes' tool registry. The schema follows the
# OpenAI function‑calling format.
registry.register(
    name="tinyfish_browser",
    toolset="browser",
    schema={
        "name": "tinyfish_browser",
        "description": "Fetch a URL using the TinyFish HTTP client and return the response as JSON.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The fully‑qualified URL to request (http or https)."},
                "timeout": {"type": "integer", "description": "Request timeout in seconds.", "default": 30},
            },
            "required": ["url"],
        },
    },
    handler=lambda args, **kw: tinyfish_browser(url=args["url"], timeout=args.get("timeout", 30)),
    check_fn=_check_requirements,
    requires_env=[],
)
