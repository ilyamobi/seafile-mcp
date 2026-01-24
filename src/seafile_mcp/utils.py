"""Utility functions for Seafile MCP server.

This module provides helper functions for file type detection,
MIME type guessing, content decoding, and size formatting.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path


# Binary file extensions (files that should not be read as text)
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".7z",
        ".rar",
        # Executables and libraries
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        # Audio/Video
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".mkv",
        ".flv",
        # Fonts
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
    }
)

# Text file extensions (files that are definitely text)
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Plain text and documentation
        ".txt",
        ".md",
        ".rst",
        ".tex",
        # Programming languages
        ".py",
        ".js",
        ".ts",
        ".sql",
        # Data formats
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".csv",
        # Web
        ".html",
        ".css",
        # Shell scripts
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        # Configuration files
        ".vim",
        ".conf",
        ".cfg",
        ".ini",
        ".toml",
        ".env",
        # Logs and misc
        ".log",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
    }
)


def is_binary_file(filename: str) -> bool:
    """Determine if a file is binary based on its extension.

    Args:
        filename: The filename or path to check.

    Returns:
        True if the file is likely binary, False if likely text.
        Returns False for unknown extensions (assumes text).

    Examples:
        >>> is_binary_file("document.pdf")
        True
        >>> is_binary_file("script.py")
        False
        >>> is_binary_file("unknown.xyz")
        False
    """
    ext = Path(filename).suffix.lower()

    if ext in BINARY_EXTENSIONS:
        return True
    if ext in TEXT_EXTENSIONS:
        return False

    # For unknown extensions, assume text (safer for MCP operations)
    return False


def get_mime_type(filename: str) -> str:
    """Guess the MIME type of a file based on its filename.

    Args:
        filename: The filename or path to check.

    Returns:
        The guessed MIME type, or "application/octet-stream" if unknown.

    Examples:
        >>> get_mime_type("document.pdf")
        'application/pdf'
        >>> get_mime_type("image.png")
        'image/png'
        >>> get_mime_type("script.py")
        'text/x-python'
    """
    # Ensure mimetypes is initialized with common types
    if not mimetypes.inited:
        mimetypes.init()

    mime_type, _ = mimetypes.guess_type(filename)

    if mime_type is None:
        # Check if it's a known text file
        if not is_binary_file(filename):
            return "text/plain"
        return "application/octet-stream"

    return mime_type


def safe_decode(content: bytes) -> tuple[str, bool]:
    """Safely decode bytes to a UTF-8 string.

    Attempts to decode the content as UTF-8. If decoding fails,
    returns an empty string with success=False.

    Args:
        content: The bytes to decode.

    Returns:
        A tuple of (decoded_string, success).
        If successful, returns the decoded string and True.
        If decoding fails, returns an empty string and False.

    Examples:
        >>> safe_decode(b"Hello, World!")
        ('Hello, World!', True)
        >>> safe_decode(b"\\xff\\xfe")  # Invalid UTF-8
        ('', False)
    """
    try:
        decoded = content.decode("utf-8")
        return decoded, True
    except UnicodeDecodeError:
        return "", False


def format_size(size_bytes: int) -> str:
    """Format a byte size into a human-readable string.

    Uses binary prefixes (KiB, MiB, GiB) for sizes >= 1024 bytes.
    Displays up to 2 decimal places, removing trailing zeros.

    Args:
        size_bytes: The size in bytes (must be non-negative).

    Returns:
        A human-readable size string.

    Examples:
        >>> format_size(0)
        '0 B'
        >>> format_size(512)
        '512 B'
        >>> format_size(1024)
        '1 KB'
        >>> format_size(1536)
        '1.5 KB'
        >>> format_size(1048576)
        '1 MB'
        >>> format_size(1572864)
        '1.5 MB'
    """
    if size_bytes < 0:
        raise ValueError("Size must be non-negative")

    if size_bytes == 0:
        return "0 B"

    # Define size units (using common KB/MB/GB notation)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]

    size = float(size_bytes)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    # Format with up to 2 decimal places, removing trailing zeros
    if size == int(size):
        return f"{int(size)} {units[unit_index]}"
    else:
        # Format to 2 decimal places and strip trailing zeros
        formatted = f"{size:.2f}".rstrip("0").rstrip(".")
        return f"{formatted} {units[unit_index]}"
