"""
NexusOps API Middleware
========================
Production middleware stack for the NexusOps FastAPI application.

Provides:
  - Request ID injection (X-Request-Id header) for distributed tracing
  - Request/response timing and logging
  - Structured access logs
"""

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("nexusops.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Inject a unique X-Request-Id header into every request/response.
    If the client sends one, reuse it. Otherwise, generate a new UUID.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))

        # Store on request state for downstream access
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id

        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Log every HTTP request with timing, method, path, and status code.
    WebSocket upgrade requests are logged but not timed.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        method = request.method
        path = request.url.path

        # Skip noisy health check logs
        if path in ("/health", "/"):
            response = await call_next(request)
            return response

        try:
            response = await call_next(request)
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            request_id = getattr(request.state, "request_id", "unknown")

            logger.info(
                f"{method} {path} → {response.status_code} "
                f"({elapsed_ms}ms) [req_id={request_id}]"
            )

            return response

        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            logger.error(f"{method} {path} → ERROR ({elapsed_ms}ms): {e}")
            raise
