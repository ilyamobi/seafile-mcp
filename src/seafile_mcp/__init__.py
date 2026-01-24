"""Seafile MCP Server - Access Seafile cloud storage from AI assistants.

This package provides an MCP (Model Context Protocol) server for interacting
with Seafile cloud storage, enabling AI assistants to manage files, directories,
and libraries.

Example usage:
    # Run the server
    python -m seafile_mcp

    # Or use the entry point
    seafile-mcp
"""

from seafile_mcp.client import SeafileAPIError, SeafileClient
from seafile_mcp.config import SeafileConfig, get_config
from seafile_mcp.server import mcp, run_server

__all__ = [
    "SeafileClient",
    "SeafileAPIError",
    "SeafileConfig",
    "get_config",
    "mcp",
    "run_server",
]

__version__ = "0.1.0"
