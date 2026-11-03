"""Prevent OAuth callback codes from appearing in Uvicorn access-log URLs."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CalendarPrivacyMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        calendar = scope["type"] == "http" and scope.get("path", "").startswith("/api/v1/calendar/")
        if not calendar:
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Routing/query parsing has completed; Uvicorn logs on response.start.
                if scope.get("path") == "/api/v1/calendar/callback":
                    scope["query_string"] = b""
                headers = list(message.get("headers", []))
                headers = [
                    (k, v)
                    for k, v in headers
                    if k.lower() not in {b"cache-control", b"referrer-policy"}
                ]
                headers.extend(
                    [(b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer")]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, private_send)
