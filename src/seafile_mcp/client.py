"""
Async Seafile API client using httpx.

This module provides an async HTTP client for interacting with the Seafile REST API.
It supports both account-based authentication (username/password) and repository-specific
API token authentication.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx


class SeafileAPIError(Exception):
    """Custom exception for Seafile API errors.

    Attributes:
        status_code: HTTP status code from the API response.
        message: Error message describing what went wrong.
        response: The original httpx.Response object, if available.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        """Initialize SeafileAPIError.

        Args:
            message: Error message describing what went wrong.
            status_code: HTTP status code from the API response.
            response: The original httpx.Response object.
        """
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format the error message with status code if available."""
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class SeafileClient:
    """Async HTTP client for the Seafile REST API.

    This client supports two authentication modes:
    1. Account authentication: Uses username/password to obtain an auth token.
       Provides full access to all accessible libraries.
    2. Repository token authentication: Uses a repo-specific API token.
       Limited to operations on the specific repository.

    Example:
        ```python
        async with SeafileClient("https://seafile.example.com") as client:
            await client.auth_with_password("user@example.com", "password")
            libraries = await client.list_libraries()
        ```
    """

    def __init__(self, server_url: str, timeout: int = 30) -> None:
        """Initialize the Seafile API client.

        Args:
            server_url: Base URL of the Seafile server (e.g., "https://seafile.example.com").
            timeout: Request timeout in seconds. Defaults to 30.
        """
        # Ensure server URL ends with a slash for proper URL joining
        self._server_url = server_url.rstrip("/") + "/"
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

        # Determine if server uses HTTPS for URL fixing
        self._use_https = server_url.lower().startswith("https://")

        # Authentication state
        self._auth_token: str | None = None
        self._repo_token: str | None = None
        self._repo_id: str | None = None

    async def __aenter__(self) -> SeafileClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    @property
    def is_authenticated(self) -> bool:
        """Check if the client has valid authentication credentials."""
        return self._auth_token is not None or self._repo_token is not None

    @property
    def is_repo_token_auth(self) -> bool:
        """Check if the client is using repository token authentication."""
        return self._repo_token is not None

    def _fix_url_scheme(self, url: str) -> str:
        """Fix URL scheme to match server configuration.

        Seafile servers behind reverse proxies may return http:// URLs
        even when accessed via https://. This method fixes the scheme.

        Args:
            url: URL returned by Seafile API.

        Returns:
            URL with corrected scheme.
        """
        if self._use_https and url.startswith("http://"):
            return "https://" + url[7:]
        return url

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication token.

        Returns:
            Dictionary of HTTP headers.

        Raises:
            SeafileAPIError: If not authenticated.
        """
        if self._repo_token:
            return {"Authorization": f"Token {self._repo_token}"}
        elif self._auth_token:
            return {"Authorization": f"Token {self._auth_token}"}
        else:
            raise SeafileAPIError(
                "Not authenticated. Call auth_with_password() or auth_with_repo_token() first."
            )

    def _build_url(self, path: str) -> str:
        """Build full URL from a path.

        Args:
            path: API endpoint path (e.g., "/api2/repos/").

        Returns:
            Full URL string.
        """
        # Remove leading slash for proper urljoin behavior
        return urljoin(self._server_url, path.lstrip("/"))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> httpx.Response:
        """Make an HTTP request to the Seafile API.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.).
            path: API endpoint path.
            params: Query parameters.
            data: Form data for POST requests.
            json_data: JSON body for POST requests.
            files: Files for multipart upload.
            authenticated: Whether to include auth headers. Defaults to True.

        Returns:
            httpx.Response object.

        Raises:
            SeafileAPIError: If the request fails or returns an error status.
        """
        url = self._build_url(path)
        headers = self._get_headers() if authenticated else {}

        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                data=data,
                json=json_data,
                files=files,
                headers=headers,
            )
        except httpx.RequestError as e:
            raise SeafileAPIError(f"Request failed: {e}") from e

        if response.status_code >= 400:
            error_msg = self._extract_error_message(response)
            raise SeafileAPIError(error_msg, status_code=response.status_code, response=response)

        return response

    def _extract_error_message(self, response: httpx.Response) -> str:
        """Extract error message from API response.

        Args:
            response: httpx.Response object.

        Returns:
            Error message string.
        """
        try:
            data = response.json()
            if isinstance(data, dict):
                # Seafile API returns errors in various formats
                return data.get("error_msg") or data.get("detail") or data.get("error") or str(data)
            return str(data)
        except Exception:
            return response.text or f"HTTP {response.status_code}"

    def _get_repo_id(self, repo_id: str | None) -> str:
        """Get repository ID, using stored one for repo-token auth if not provided.

        Args:
            repo_id: Repository ID, or None to use stored ID.

        Returns:
            Repository ID string.

        Raises:
            SeafileAPIError: If repo_id is required but not available.
        """
        if repo_id:
            return repo_id
        if self._repo_id:
            return self._repo_id
        raise SeafileAPIError("Repository ID is required")

    # -------------------------------------------------------------------------
    # Authentication Methods
    # -------------------------------------------------------------------------

    async def auth_with_password(self, username: str, password: str) -> None:
        """Authenticate with username and password.

        This method obtains an authentication token from the Seafile server
        using the provided credentials. The token is stored internally and
        used for subsequent API requests.

        Args:
            username: Seafile account username (usually an email address).
            password: Seafile account password.

        Raises:
            SeafileAPIError: If authentication fails.
        """
        response = await self._request(
            "POST",
            "/api2/auth-token/",
            data={"username": username, "password": password},
            authenticated=False,
        )

        data = response.json()
        token = data.get("token")
        if not token:
            raise SeafileAPIError("Authentication failed: No token in response")

        self._auth_token = token
        # Clear repo token auth if switching to password auth
        self._repo_token = None
        self._repo_id = None

    async def auth_with_repo_token(self, repo_token: str, repo_id: str) -> None:
        """Set up authentication with a repository-specific API token.

        Repository tokens provide limited access to a specific library.
        When using repo-token authentication, the client will automatically
        use the via-repo-token API endpoints.

        Args:
            repo_token: Repository API token.
            repo_id: Repository/library ID associated with the token.
        """
        self._repo_token = repo_token
        self._repo_id = repo_id
        # Clear account auth if switching to repo token auth
        self._auth_token = None

    # -------------------------------------------------------------------------
    # Library Operations
    # -------------------------------------------------------------------------

    async def list_libraries(self) -> list[dict[str, Any]]:
        """List all accessible libraries.

        This method is only available with account authentication.
        Repository token authentication does not support listing libraries.

        Returns:
            List of library dictionaries containing library metadata.

        Raises:
            SeafileAPIError: If using repo-token auth or request fails.
        """
        if self.is_repo_token_auth:
            raise SeafileAPIError(
                "list_libraries() is not available with repository token authentication"
            )

        response = await self._request("GET", "/api2/repos/")
        return response.json()

    async def get_library_info(self, repo_id: str | None = None) -> dict[str, Any]:
        """Get library/repository details.

        Args:
            repo_id: Repository ID. Optional for repo-token auth (uses stored ID).

        Returns:
            Dictionary containing library metadata including name, owner,
            size, encrypted status, etc.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request("GET", "/api/v2.1/via-repo-token/repo-info/")
        else:
            response = await self._request("GET", f"/api2/repos/{repo_id}/")

        return response.json()

    # -------------------------------------------------------------------------
    # Directory Operations
    # -------------------------------------------------------------------------

    async def list_directory(
        self, repo_id: str | None = None, path: str = "/"
    ) -> list[dict[str, Any]]:
        """List contents of a directory.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Directory path within the repository. Defaults to root "/".

        Returns:
            List of dictionaries representing files and subdirectories.
            Each entry contains name, type, size, mtime, etc.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "GET",
                "/api/v2.1/via-repo-token/dir/",
                params={"path": path},
            )
        else:
            response = await self._request(
                "GET",
                f"/api/v2.1/repos/{repo_id}/dir/",
                params={"p": path},
            )

        data = response.json()
        # API may return {"dirent_list": [...]} or just [...]
        if isinstance(data, dict) and "dirent_list" in data:
            dirent_list: list[dict[str, Any]] = data["dirent_list"]
            return dirent_list
        if isinstance(data, list):
            return list(data)
        return []

    async def create_directory(self, repo_id: str | None = None, path: str = "/") -> dict[str, Any]:
        """Create a new directory.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Full path for the new directory (e.g., "/documents/reports").

        Returns:
            Dictionary containing the created directory info.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "POST",
                "/api/v2.1/via-repo-token/dir/",
                params={"path": path},
                data={"operation": "mkdir"},
            )
        else:
            response = await self._request(
                "POST",
                f"/api/v2.1/repos/{repo_id}/dir/",
                params={"p": path},
                data={"operation": "mkdir"},
            )

        return response.json()

    async def delete_directory(self, repo_id: str | None = None, path: str = "/") -> bool:
        """Delete a directory.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Path to the directory to delete.

        Returns:
            True if deletion was successful.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            await self._request(
                "DELETE",
                "/api/v2.1/via-repo-token/dir/",
                params={"path": path},
            )
        else:
            await self._request(
                "DELETE",
                f"/api/v2.1/repos/{repo_id}/dir/",
                params={"p": path},
            )

        return True

    # -------------------------------------------------------------------------
    # File Operations
    # -------------------------------------------------------------------------

    async def get_file_info(self, repo_id: str | None = None, path: str = "/") -> dict[str, Any]:
        """Get file metadata/details.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Path to the file within the repository.

        Returns:
            Dictionary containing file metadata including name, size,
            mtime, type, etc.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "GET",
                "/api/v2.1/via-repo-token/file/",
                params={"path": path},
            )
        else:
            response = await self._request(
                "GET",
                f"/api2/repos/{repo_id}/file/detail/",
                params={"p": path},
            )

        return response.json()

    async def get_download_link(self, repo_id: str | None = None, path: str = "/") -> str:
        """Get a temporary download URL for a file.

        The download link is temporary and expires after a short time.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Path to the file within the repository.

        Returns:
            Temporary download URL string.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "GET",
                "/api/v2.1/via-repo-token/download-link/",
                params={"path": path},
            )
        else:
            response = await self._request(
                "GET",
                f"/api2/repos/{repo_id}/file/",
                params={"p": path},
            )

        # Response is a quoted URL string
        download_url = response.text.strip().strip('"')
        return self._fix_url_scheme(download_url)

    async def download_file(self, repo_id: str | None = None, path: str = "/") -> bytes:
        """Download file content.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Path to the file within the repository.

        Returns:
            File content as bytes.

        Raises:
            SeafileAPIError: If the request fails.
        """
        download_url = await self.get_download_link(repo_id, path)

        try:
            response = await self._client.get(download_url, headers=self._get_headers())
            response.raise_for_status()
            return response.content
        except httpx.RequestError as e:
            raise SeafileAPIError(f"Failed to download file: {e}") from e
        except httpx.HTTPStatusError as e:
            raise SeafileAPIError(
                f"Failed to download file: {e}",
                status_code=e.response.status_code,
                response=e.response,
            ) from e

    async def get_upload_link(self, repo_id: str | None = None, parent_dir: str = "/") -> str:
        """Get an upload link for uploading files.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            parent_dir: Parent directory where files will be uploaded.

        Returns:
            Upload URL string.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "GET",
                "/api/v2.1/via-repo-token/upload-link/",
                params={"path": parent_dir},
            )
        else:
            response = await self._request(
                "GET",
                f"/api2/repos/{repo_id}/upload-link/",
                params={"p": parent_dir},
            )

        upload_url = response.text.strip().strip('"')
        return self._fix_url_scheme(upload_url)

    async def upload_file(
        self,
        repo_id: str | None = None,
        parent_dir: str = "/",
        filename: str = "",
        content: bytes = b"",
    ) -> dict[str, Any]:
        """Upload a file to the repository.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            parent_dir: Parent directory to upload the file to.
            filename: Name of the file to create.
            content: File content as bytes.

        Returns:
            Dictionary containing uploaded file info.

        Raises:
            SeafileAPIError: If the request fails.
        """
        upload_url = await self.get_upload_link(repo_id, parent_dir)

        files = {"file": (filename, content)}
        data = {"parent_dir": parent_dir, "replace": "1"}

        try:
            response = await self._client.post(
                upload_url,
                files=files,
                data=data,
                headers=self._get_headers(),
            )
            response.raise_for_status()
        except httpx.RequestError as e:
            raise SeafileAPIError(f"Failed to upload file: {e}") from e
        except httpx.HTTPStatusError as e:
            raise SeafileAPIError(
                f"Failed to upload file: {e}",
                status_code=e.response.status_code,
                response=e.response,
            ) from e

        # Response may be JSON or plain text with the filename
        try:
            return response.json()
        except Exception:
            return {"filename": filename, "response": response.text}

    async def create_file(self, repo_id: str | None = None, path: str = "/") -> dict[str, Any]:
        """Create an empty file.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Full path for the new file (e.g., "/documents/newfile.txt").

        Returns:
            Dictionary containing created file info.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "POST",
                "/api/v2.1/via-repo-token/file/",
                params={"path": path},
                data={"operation": "create"},
            )
        else:
            response = await self._request(
                "POST",
                f"/api2/repos/{repo_id}/file/",
                params={"p": path},
                data={"operation": "create"},
            )

        # Response might be empty or contain file info
        if response.text:
            try:
                return response.json()
            except Exception:
                return {"path": path, "success": True}
        return {"path": path, "success": True}

    async def delete_file(self, repo_id: str | None = None, path: str = "/") -> bool:
        """Delete a file.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Path to the file to delete.

        Returns:
            True if deletion was successful.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            await self._request(
                "DELETE",
                "/api/v2.1/via-repo-token/file/",
                params={"path": path},
            )
        else:
            await self._request(
                "DELETE",
                f"/api2/repos/{repo_id}/file/",
                params={"p": path},
            )

        return True

    async def rename_file(
        self,
        repo_id: str | None = None,
        path: str = "/",
        new_name: str = "",
    ) -> dict[str, Any]:
        """Rename a file.

        Args:
            repo_id: Repository ID. Optional for repo-token auth.
            path: Current path to the file.
            new_name: New filename (not full path, just the filename).

        Returns:
            Dictionary containing renamed file info.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)

        if self.is_repo_token_auth:
            response = await self._request(
                "POST",
                "/api/v2.1/via-repo-token/file/",
                params={"path": path},
                data={"operation": "rename", "newname": new_name},
            )
        else:
            response = await self._request(
                "POST",
                f"/api2/repos/{repo_id}/file/",
                params={"p": path},
                data={"operation": "rename", "newname": new_name},
            )

        try:
            return response.json()
        except Exception:
            return {"path": path, "new_name": new_name, "success": True}

    async def move_file(
        self,
        repo_id: str | None = None,
        src_path: str = "/",
        dst_dir: str = "/",
        dst_repo_id: str | None = None,
    ) -> dict[str, Any]:
        """Move a file to another directory.

        Args:
            repo_id: Source repository ID. Optional for repo-token auth.
            src_path: Source file path.
            dst_dir: Destination directory path.
            dst_repo_id: Destination repository ID. If None, same as source repo.

        Returns:
            Dictionary containing move operation result.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)
        dst_repo_id = dst_repo_id or repo_id

        if self.is_repo_token_auth:
            response = await self._request(
                "POST",
                "/api/v2.1/via-repo-token/file/",
                params={"path": src_path},
                data={
                    "operation": "move",
                    "dst_dir": dst_dir,
                    "dst_repo": dst_repo_id,
                },
            )
        else:
            response = await self._request(
                "POST",
                f"/api2/repos/{repo_id}/file/",
                params={"p": src_path},
                data={
                    "operation": "move",
                    "dst_dir": dst_dir,
                    "dst_repo": dst_repo_id,
                },
            )

        try:
            return response.json()
        except Exception:
            return {"src_path": src_path, "dst_dir": dst_dir, "success": True}

    async def copy_file(
        self,
        repo_id: str | None = None,
        src_path: str = "/",
        dst_dir: str = "/",
        dst_repo_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy a file to another directory.

        Args:
            repo_id: Source repository ID. Optional for repo-token auth.
            src_path: Source file path.
            dst_dir: Destination directory path.
            dst_repo_id: Destination repository ID. If None, same as source repo.

        Returns:
            Dictionary containing copy operation result.

        Raises:
            SeafileAPIError: If the request fails.
        """
        repo_id = self._get_repo_id(repo_id)
        dst_repo_id = dst_repo_id or repo_id

        if self.is_repo_token_auth:
            response = await self._request(
                "POST",
                "/api/v2.1/via-repo-token/file/",
                params={"path": src_path},
                data={
                    "operation": "copy",
                    "dst_dir": dst_dir,
                    "dst_repo": dst_repo_id,
                },
            )
        else:
            response = await self._request(
                "POST",
                f"/api2/repos/{repo_id}/file/",
                params={"p": src_path},
                data={
                    "operation": "copy",
                    "dst_dir": dst_dir,
                    "dst_repo": dst_repo_id,
                },
            )

        try:
            return response.json()
        except Exception:
            return {"src_path": src_path, "dst_dir": dst_dir, "success": True}

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    async def search_files(
        self,
        query: str,
        repo_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search files by name or content.

        Args:
            query: Search query string.
            repo_id: Optional repository ID to limit search scope.
                     For repo-token auth, defaults to the authenticated repo.

        Returns:
            List of dictionaries containing matching file info.

        Raises:
            SeafileAPIError: If the request fails.
        """
        params: dict[str, Any] = {"q": query}

        if self.is_repo_token_auth:
            # For repo-token auth, search is limited to the authenticated repo
            response = await self._request(
                "GET",
                "/api/v2.1/via-repo-token/search-file/",
                params=params,
            )
        else:
            if repo_id:
                params["search_repo"] = repo_id
            response = await self._request(
                "GET",
                "/api2/search/",
                params=params,
            )

        data = response.json()
        # API may return {"results": [...]} or just [...]
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        if isinstance(data, list):
            return data
        return []
