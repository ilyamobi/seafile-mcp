"""Entry point for running the Seafile MCP server."""

from __future__ import annotations

import sys

from dotenv import load_dotenv


def main() -> None:
    """Run the Seafile MCP server."""
    # Load environment variables from .env file
    load_dotenv()

    try:
        # Import here to ensure .env is loaded first
        from seafile_mcp.server import mcp

        # Run with stdio transport (default for MCP)
        mcp.run()
    except ValueError as e:
        # Configuration errors (missing credentials, invalid values)
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        # Missing dependencies
        print(f"Import error: {e}", file=sys.stderr)
        print("Please ensure all dependencies are installed: pip install -e .", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        pass
    except Exception as e:
        # Unexpected errors
        print(f"Failed to start Seafile MCP server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
