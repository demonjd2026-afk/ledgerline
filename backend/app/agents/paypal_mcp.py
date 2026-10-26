"""PayPal's official MCP server as the agent's PayPal tool source.

Runs ``@paypal/mcp`` (the server behind PayPal's Agent Toolkit) over stdio with a sandbox OAuth
token minted by our own client, restricted to read-only tools. Tools are wrapped so the sync
graph can call them. If Node or the package is unavailable, the graph falls back to the native
read tools in ``tools.py`` and says so in the trace.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from app.config import get_settings
from app.logging import get_logger
from app.paypal.client import PayPalClient

log = get_logger("agent.paypal_mcp")

READ_ONLY_TOOLS = "orders.get,disputes.get,disputes.list,invoices.get,invoices.list,transactions.list,shipment.get"
_REL = Path("node_modules") / "@paypal" / "mcp" / "dist" / "index.js"


def _server_js() -> Path:
    """Locate @paypal/mcp: explicit PAYPAL_MCP_SERVER_JS, else next to the source tree (dev), else the
    working directory (the Docker image installs node_modules in /app/backend and runs from there)."""
    explicit = os.environ.get("PAYPAL_MCP_SERVER_JS")
    if explicit:
        return Path(explicit)
    for base in (Path(__file__).resolve().parents[2], Path.cwd()):
        if (base / _REL).exists():
            return base / _REL
    return Path(__file__).resolve().parents[2] / _REL


SERVER_JS = _server_js()


def available() -> bool:
    return get_settings().paypal_mcp_enabled and shutil.which("node") is not None and SERVER_JS.exists()


def load_paypal_mcp_tools(paypal: PayPalClient) -> list[StructuredTool]:
    """Start the server, list tools, return sync wrappers. Returns [] on any failure."""
    if not available():
        return []
    try:
        return asyncio.run(_load(paypal))
    except Exception as exc:  # noqa: BLE001
        log.warning("paypal_mcp.unavailable", error=str(exc))
        return []


async def _load(paypal: PayPalClient) -> list[StructuredTool]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    token = paypal._get_token()
    env = dict(os.environ)
    env.update({"PAYPAL_ACCESS_TOKEN": token, "PAYPAL_ENVIRONMENT": "SANDBOX" if get_settings().paypal_env == "sandbox" else "PRODUCTION"})
    client = MultiServerMCPClient(
        {
            "paypal": {
                "transport": "stdio",
                "command": "node",
                "args": [str(SERVER_JS), f"--tools={READ_ONLY_TOOLS}"],
                "env": env,
            }
        }
    )
    async_tools = await client.get_tools()
    wrapped: list[StructuredTool] = []
    for t in async_tools:
        wrapped.append(_sync_wrapper(t))
    log.info("paypal_mcp.loaded", tools=[t.name for t in wrapped])
    return wrapped


def _sync_wrapper(tool) -> StructuredTool:
    async_tool = tool

    def _run(**kwargs: Any) -> str:
        try:
            result = asyncio.run(async_tool.ainvoke(kwargs))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return str(result)

    return StructuredTool.from_function(
        func=_run,
        name=f"paypal_mcp_{tool.name}",
        description=f"[PayPal MCP] {tool.description}",
        args_schema=tool.args_schema,
    )
