"""FastMCP server implementation for Seafile cloud storage.

This module provides the MCP server with tools for interacting with Seafile,
including file/directory operations, library management, and search.
"""

from __future__ import annotations

import base64
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from seafile_mcp.client import SeafileClient
from seafile_mcp.config import get_config
from seafile_mcp.utils import format_size, get_mime_type, is_binary_file, safe_decode


# Initialize FastMCP server
mcp = FastMCP(
    "Seafile MCP",
    instructions="Access Seafile cloud storage from AI assistants",
)


# =============================================================================
# Pydantic Response Models
# =============================================================================


class Library(BaseModel):
    """Represents a Seafile library (repository)."""

    id: str = Field(description="Unique library identifier")
    name: str = Field(description="Library name")
    owner: str = Field(default="", description="Library owner username")
    size: int = Field(default=0, description="Total size in bytes")
    encrypted: bool = Field(default=False, description="Whether the library is encrypted")
    permission: str = Field(default="r", description="User's permission level (r, rw)")
    mtime: int | str = Field(default=0, description="Last modification timestamp")


class DirEntry(BaseModel):
    """Represents a file or directory entry."""

    name: str = Field(description="Entry name")
    type: str = Field(description="Entry type: 'file' or 'dir'")
    size: int = Field(default=0, description="Size in bytes (0 for directories)")
    mtime: int | str = Field(description="Last modification timestamp")
    permission: str = Field(default="r", description="Permission level")


class FileContent(BaseModel):
    """Represents file content or download information."""

    path: str = Field(description="File path in the library")
    name: str = Field(description="File name")
    size: int = Field(description="File size in bytes")
    mtime: int | str = Field(description="Last modification timestamp")
    content: Optional[str] = Field(default=None, description="Text content (if readable)")
    download_url: Optional[str] = Field(
        default=None, description="Temporary download URL (for binary/large files)"
    )
    is_binary: bool = Field(description="Whether the file is binary")
    truncated: bool = Field(default=False, description="Whether content was truncated")
    message: str = Field(description="Status message")


class FileInfo(BaseModel):
    """Represents file metadata."""

    path: str = Field(description="File path in the library")
    name: str = Field(description="File name")
    size: int = Field(description="File size in bytes")
    mtime: int | str = Field(description="Last modification timestamp")
    mime_type: str = Field(description="MIME type of the file")


class OperationResult(BaseModel):
    """Represents the result of a file/directory operation."""

    success: bool = Field(description="Whether the operation succeeded")
    message: str = Field(description="Result message")
    path: Optional[str] = Field(default=None, description="Affected path (if applicable)")


# =============================================================================
# Client Management
# =============================================================================

_client: Optional[SeafileClient] = None


async def get_client() -> SeafileClient:
    """Get an authenticated Seafile client instance.

    Creates and authenticates a client on first call, then returns the cached instance.
    Supports both account-based and repository token authentication.

    Returns:
        Authenticated SeafileClient instance.

    Raises:
        Exception: If authentication fails.
    """
    global _client
    if _client is None:
        config = get_config()
        _client = SeafileClient(config.server_url, config.timeout)

        if config.has_account_auth:
            # Config validation guarantees these are non-None when has_account_auth is True
            username = config.username
            password = config.password
            if username is None or password is None:
                raise ValueError("Username and password required for account auth")
            await _client.auth_with_password(username, password)
        else:
            # Config validation guarantees these are non-None when has_repo_token_auth is True
            repo_token = config.repo_token
            repo_id = config.repo_id
            if repo_token is None or repo_id is None:
                raise ValueError("Repo token and repo ID required for repo token auth")
            await _client.auth_with_repo_token(repo_token, repo_id)

    return _client


def resolve_repo_id(repo_id: Optional[str] = None) -> str:
    """Resolve repository ID, using config default for repo-token auth if not provided.

    Args:
        repo_id: Optional repository ID. If None and using repo-token auth,
                 uses the configured repo_id.

    Returns:
        The resolved repository ID.

    Raises:
        ValueError: If no repo_id is provided and none is configured.
    """
    if repo_id:
        return repo_id

    config = get_config()
    if config.repo_id:
        return config.repo_id

    raise ValueError("repo_id is required (no default configured)")


# =============================================================================
# Library Tools
# =============================================================================


@mcp.tool()
async def seafile_list_libraries() -> list[Library]:
    """List all accessible Seafile libraries.

    Returns a list of all libraries (repositories) the authenticated user has access to.
    Note: This operation requires account-based authentication and may not work
    with repository token authentication.

    Returns:
        List of Library objects containing library metadata.
    """
    try:
        client = await get_client()
        libraries = await client.list_libraries()

        return [
            Library(
                id=lib["id"],
                name=lib["name"],
                owner=lib.get("owner", ""),
                size=lib.get("size", 0),
                encrypted=lib.get("encrypted", False),
                permission=lib.get("permission", "r"),
                mtime=lib.get("mtime", 0),
            )
            for lib in libraries
        ]
    except Exception as e:
        # Return empty list with error context for repo-token auth
        raise ValueError(f"Failed to list libraries: {e}") from e


@mcp.tool()
async def seafile_get_library_info(
    repo_id: str = Field(description="Library/repository ID"),
) -> Library:
    """Get information about a specific library.

    Args:
        repo_id: The unique identifier of the library.

    Returns:
        Library object containing detailed library metadata.
    """
    try:
        client = await get_client()
        lib = await client.get_library_info(repo_id)

        return Library(
            id=lib["id"],
            name=lib["name"],
            owner=lib.get("owner", ""),
            size=lib.get("size", 0),
            encrypted=lib.get("encrypted", False),
            permission=lib.get("permission", "r"),
            mtime=lib.get("mtime", 0),
        )
    except Exception as e:
        raise ValueError(f"Failed to get library info: {e}") from e


# =============================================================================
# Directory Tools
# =============================================================================


@mcp.tool()
async def seafile_list_directory(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(default="/", description="Directory path within the library"),
) -> list[DirEntry]:
    """List files and folders in a directory.

    Args:
        repo_id: The library/repository ID.
        path: The directory path to list (default: root "/").

    Returns:
        List of DirEntry objects for files and subdirectories.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        entries = await client.list_directory(resolved_repo_id, path)

        return [
            DirEntry(
                name=entry["name"],
                type=entry.get("type", "file"),
                size=entry.get("size", 0),
                mtime=entry.get("mtime", 0),
                permission=entry.get("permission", "r"),
            )
            for entry in entries
        ]
    except Exception as e:
        raise ValueError(f"Failed to list directory: {e}") from e


@mcp.tool()
async def seafile_create_directory(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="Full path of directory to create"),
) -> OperationResult:
    """Create a new directory in a Seafile library.

    Args:
        repo_id: The library/repository ID.
        path: The full path of the directory to create.

    Returns:
        OperationResult indicating success or failure.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        await client.create_directory(resolved_repo_id, path)

        return OperationResult(
            success=True,
            message=f"Directory created successfully",
            path=path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to create directory: {e}",
            path=path,
        )


# =============================================================================
# File Reading Tools
# =============================================================================


@mcp.tool()
async def seafile_read_file(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="File path within the library"),
) -> FileContent:
    """Read a file from Seafile.

    For text files within the size limit, returns the file content directly.
    For binary files or files exceeding the size limit, returns a download URL.

    Args:
        repo_id: The library/repository ID.
        path: The path to the file within the library.

    Returns:
        FileContent with either text content or a download URL.
    """
    config = get_config()

    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()

        # Get file metadata first
        file_info = await client.get_file_info(resolved_repo_id, path)
        file_size = file_info.get("size", 0)
        file_mtime = file_info.get("mtime", 0)
        file_name = file_info.get("name", path.split("/")[-1])

        # Check if file is binary
        binary = is_binary_file(file_name)

        # For binary files or files too large, return download URL
        if binary or file_size > config.max_read_size:
            download_url = await client.get_download_link(resolved_repo_id, path)

            if binary:
                message = f"Binary file ({format_size(file_size)}). Use download URL to retrieve."
            else:
                message = (
                    f"File too large ({format_size(file_size)} > "
                    f"{format_size(config.max_read_size)}). Use download URL to retrieve."
                )

            return FileContent(
                path=path,
                name=file_name,
                size=file_size,
                mtime=file_mtime,
                content=None,
                download_url=download_url,
                is_binary=binary,
                truncated=False,
                message=message,
            )

        # Download and decode text content
        content_bytes = await client.download_file(resolved_repo_id, path)
        content_str, decode_success = safe_decode(content_bytes)

        if not decode_success:
            # File appears to be binary despite extension
            download_url = await client.get_download_link(resolved_repo_id, path)
            return FileContent(
                path=path,
                name=file_name,
                size=file_size,
                mtime=file_mtime,
                content=None,
                download_url=download_url,
                is_binary=True,
                truncated=False,
                message="File could not be decoded as text. Use download URL to retrieve.",
            )

        return FileContent(
            path=path,
            name=file_name,
            size=file_size,
            mtime=file_mtime,
            content=content_str,
            download_url=None,
            is_binary=False,
            truncated=False,
            message="File content retrieved successfully",
        )

    except Exception as e:
        raise ValueError(f"Failed to read file: {e}") from e


@mcp.tool()
async def seafile_get_file_info(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="File path within the library"),
) -> FileInfo:
    """Get metadata about a file.

    Args:
        repo_id: The library/repository ID.
        path: The path to the file within the library.

    Returns:
        FileInfo containing file metadata including size, mtime, and MIME type.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        file_detail = await client.get_file_info(resolved_repo_id, path)

        file_name = file_detail.get("name", path.split("/")[-1])

        return FileInfo(
            path=path,
            name=file_name,
            size=file_detail.get("size", 0),
            mtime=file_detail.get("mtime", 0),
            mime_type=get_mime_type(file_name),
        )
    except Exception as e:
        raise ValueError(f"Failed to get file info: {e}") from e


@mcp.tool()
async def seafile_get_download_link(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="File path within the library"),
) -> str:
    """Get a temporary download URL for a file.

    The download URL is typically valid for a limited time (usually 1 hour).

    Args:
        repo_id: The library/repository ID.
        path: The path to the file within the library.

    Returns:
        Temporary download URL string.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        return await client.get_download_link(resolved_repo_id, path)
    except Exception as e:
        raise ValueError(f"Failed to get download link: {e}") from e


# =============================================================================
# File Writing Tools
# =============================================================================


@mcp.tool()
async def seafile_write_file(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="File path within the library"),
    content: str = Field(description="Text content to write to the file"),
) -> OperationResult:
    """Create or update a text file in Seafile.

    If the file exists, it will be overwritten. If it doesn't exist, it will be created.
    Parent directories must exist.

    Args:
        repo_id: The library/repository ID.
        path: The path where the file should be written.
        content: The text content to write.

    Returns:
        OperationResult indicating success or failure.
    """
    config = get_config()

    try:
        # Check content size
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > config.max_write_size:
            return OperationResult(
                success=False,
                message=(
                    f"Content too large ({format_size(len(content_bytes))} > "
                    f"{format_size(config.max_write_size)})"
                ),
                path=path,
            )

        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()

        # Split path into parent directory and filename
        path_parts = path.rstrip("/").rsplit("/", 1)
        if len(path_parts) == 2:
            parent_dir, filename = path_parts[0] or "/", path_parts[1]
        else:
            parent_dir, filename = "/", path_parts[0]

        await client.upload_file(resolved_repo_id, parent_dir, filename, content_bytes)

        return OperationResult(
            success=True,
            message=f"File written successfully ({format_size(len(content_bytes))})",
            path=path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to write file: {e}",
            path=path,
        )


@mcp.tool()
async def seafile_upload_file(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="File path within the library"),
    base64_content: str = Field(description="Base64 encoded file content"),
) -> OperationResult:
    """Upload a binary file to Seafile.

    Use this for uploading binary files by providing the content as base64.
    For text files, prefer seafile_write_file instead.

    Args:
        repo_id: The library/repository ID.
        path: The path where the file should be uploaded.
        base64_content: The file content encoded as base64.

    Returns:
        OperationResult indicating success or failure.
    """
    config = get_config()

    try:
        # Decode base64 content
        try:
            content_bytes = base64.b64decode(base64_content)
        except Exception:
            return OperationResult(
                success=False,
                message="Invalid base64 content",
                path=path,
            )

        # Check content size
        if len(content_bytes) > config.max_write_size:
            return OperationResult(
                success=False,
                message=(
                    f"Content too large ({format_size(len(content_bytes))} > "
                    f"{format_size(config.max_write_size)})"
                ),
                path=path,
            )

        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()

        # Split path into parent directory and filename
        path_parts = path.rstrip("/").rsplit("/", 1)
        if len(path_parts) == 2:
            parent_dir, filename = path_parts[0] or "/", path_parts[1]
        else:
            parent_dir, filename = "/", path_parts[0]

        await client.upload_file(resolved_repo_id, parent_dir, filename, content_bytes)

        return OperationResult(
            success=True,
            message=f"File uploaded successfully ({format_size(len(content_bytes))})",
            path=path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to upload file: {e}",
            path=path,
        )


# =============================================================================
# File Management Tools
# =============================================================================


@mcp.tool()
async def seafile_delete(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="Path of file or directory to delete"),
) -> OperationResult:
    """Delete a file or directory from Seafile.

    Warning: This operation is irreversible. Deleted items may be recoverable
    from the library's trash for a limited time, depending on server settings.

    Args:
        repo_id: The library/repository ID.
        path: The path to the file or directory to delete.

    Returns:
        OperationResult indicating success or failure.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        await client.delete_file(resolved_repo_id, path)

        return OperationResult(
            success=True,
            message="Deleted successfully",
            path=path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to delete: {e}",
            path=path,
        )


@mcp.tool()
async def seafile_move(
    repo_id: str = Field(description="Library/repository ID"),
    src_path: str = Field(description="Source path of file or directory"),
    dst_path: str = Field(description="Destination path (directory where item will be moved)"),
) -> OperationResult:
    """Move a file or directory within a Seafile library.

    Args:
        repo_id: The library/repository ID.
        src_path: The current path of the file or directory.
        dst_path: The destination directory path.

    Returns:
        OperationResult indicating success or failure.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        await client.move_file(resolved_repo_id, src_path, dst_path)

        return OperationResult(
            success=True,
            message=f"Moved successfully to {dst_path}",
            path=src_path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to move: {e}",
            path=src_path,
        )


@mcp.tool()
async def seafile_copy(
    repo_id: str = Field(description="Library/repository ID"),
    src_path: str = Field(description="Source path of file or directory"),
    dst_path: str = Field(description="Destination path (directory where copy will be placed)"),
) -> OperationResult:
    """Copy a file or directory within a Seafile library.

    Args:
        repo_id: The library/repository ID.
        src_path: The path of the file or directory to copy.
        dst_path: The destination directory path.

    Returns:
        OperationResult indicating success or failure.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        await client.copy_file(resolved_repo_id, src_path, dst_path)

        return OperationResult(
            success=True,
            message=f"Copied successfully to {dst_path}",
            path=src_path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to copy: {e}",
            path=src_path,
        )


@mcp.tool()
async def seafile_rename(
    repo_id: str = Field(description="Library/repository ID"),
    path: str = Field(description="Path of file or directory to rename"),
    new_name: str = Field(description="New name for the file or directory"),
) -> OperationResult:
    """Rename a file or directory in Seafile.

    Args:
        repo_id: The library/repository ID.
        path: The current path of the file or directory.
        new_name: The new name (not a path, just the name).

    Returns:
        OperationResult indicating success or failure.
    """
    try:
        resolved_repo_id = resolve_repo_id(repo_id)
        client = await get_client()
        await client.rename_file(resolved_repo_id, path, new_name)

        # Calculate new path for the message
        parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
        new_path = f"{parent.rstrip('/')}/{new_name}"

        return OperationResult(
            success=True,
            message=f"Renamed successfully to {new_name}",
            path=new_path,
        )
    except Exception as e:
        return OperationResult(
            success=False,
            message=f"Failed to rename: {e}",
            path=path,
        )


# =============================================================================
# Search Tool
# =============================================================================


@mcp.tool()
async def seafile_search(
    query: str = Field(description="Search query string"),
    repo_id: Optional[str] = Field(
        default=None, description="Limit search to specific library (optional)"
    ),
) -> list[dict]:
    """Search for files by name across Seafile libraries.

    Searches file and folder names matching the query string.
    Note: Search functionality depends on server configuration and may
    not be available on all Seafile installations.

    Args:
        query: The search query string.
        repo_id: Optional library ID to limit search scope.

    Returns:
        List of dictionaries containing search results with file information.
    """
    try:
        resolved_repo_id = None
        if repo_id:
            resolved_repo_id = resolve_repo_id(repo_id)
        elif get_config().repo_id:
            # Use configured repo_id for repo-token auth
            resolved_repo_id = get_config().repo_id

        client = await get_client()
        results = await client.search_files(query, resolved_repo_id)

        return results
    except Exception as e:
        raise ValueError(f"Search failed: {e}") from e


# =============================================================================
# Server Entry Point
# =============================================================================


def run_server() -> None:
    """Run the Seafile MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_server()
