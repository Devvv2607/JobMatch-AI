"""Request middleware: request id, timing, access log, metrics and security headers.

Written as plain ASGI rather than BaseHTTPMiddleware so that streaming responses (SSE)
pass through unbuffered.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var
from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = logging.getLogger("app.request")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UNOBSERVED_PATHS = frozenset({"/metrics", "/healthz", "/readyz"})
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        # Not reset afterwards: the outermost error handler still needs it to build the
        # 500 envelope, and each request runs in its own context.
        request_id_var.set(request_id)

        path: str = scope["path"]
        status = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                out["Server-Timing"] = f"app;dur={(time.perf_counter() - start) * 1000:.1f}"
                out["X-Content-Type-Options"] = "nosniff"
                out["X-Frame-Options"] = "DENY"
                out["Referrer-Policy"] = "no-referrer"
                out["Cross-Origin-Resource-Policy"] = "same-site"
                if path not in _DOCS_PATHS:
                    out["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                    out.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    out["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            route_path = _route_template(scope)
            if path not in _UNOBSERVED_PATHS:
                HTTP_REQUESTS.labels(scope["method"], route_path, str(status)).inc()
                HTTP_DURATION.labels(scope["method"], route_path).observe(duration)
                logger.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": path,
                        "route": route_path,
                        "status": status,
                        "duration_ms": round(duration * 1000, 2),
                    },
                )


def _route_template(scope: Scope) -> str:
    """The matched route with parameter values replaced by their names, e.g.
    /api/v1/tasks/{task_id}. Used as a metric label so cardinality stays bounded.

    Built from the path and its parameters rather than from `route.path`, which
    omits the prefixes of enclosing routers.
    """
    if scope.get("route") is None:
        return "unmatched"
    names = {str(value): name for name, value in scope.get("path_params", {}).items()}
    segments = scope["path"].split("/")
    return "/".join(f"{{{names[s]}}}" if s in names else s for s in segments)
