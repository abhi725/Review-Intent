"""Bearer-token gate for the mounted MCP endpoint.

The dashboard authenticates with a Google OAuth session cookie, which an MCP
client cannot obtain — there is no browser to redirect. So the MCP mount gets
its own bearer check.

This is a plain ASGI wrapper rather than a FastAPI dependency because the MCP
app is mounted as a sub-application; route dependencies declared on the parent
never run for it.
"""

import secrets
from typing import Any, Callable


class NormalizeMountPath:
    """Make a bare `/mcp` behave like `/mcp/`.

    A Starlette Mount only matches its own path with a trailing slash. Without
    this, `POST /mcp` misses the mount and falls through to the static handler,
    which answers 405 — a confusing error for a client that did nothing wrong.
    Rewriting in middleware keeps both spellings working.
    """

    def __init__(self, app: Callable, mount: str = "/mcp"):
        self.app = app
        self.mount = mount

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == self.mount:
            scope = dict(scope)
            scope["path"] = self.mount + "/"
            raw = scope.get("raw_path")
            if raw:
                scope["raw_path"] = raw + b"/"
        await self.app(scope, receive, send)


class BearerAuthASGI:
    def __init__(self, app: Callable, token: str, realm: str = "intent-desk-mcp"):
        self.app = app
        self.token = token or ""
        self.realm = realm

    async def _deny(self, send: Callable, status: int, message: str) -> None:
        body = message.encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", f'Bearer realm="{self.realm}"'.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # An unset token means the endpoint is unconfigured, not open. Refusing
        # is the safe default: a blank token must never authenticate anyone.
        if not self.token:
            await self._deny(send, 503, "MCP endpoint has no bearer token configured")
            return

        header = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                header = value.decode("latin-1")
                break

        # compare_digest to keep the check constant-time.
        if not secrets.compare_digest(header.strip(), f"Bearer {self.token}"):
            await self._deny(send, 401, "Unauthorized")
            return

        await self.app(scope, receive, send)
