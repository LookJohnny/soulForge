"""Request ID middleware — generates or propagates a unique request ID per request.

If the client sends an `X-Request-ID` header, it is reused. Otherwise a new
UUID4 is generated. The ID is stored in `request.state.request_id` and added
to the response as an `X-Request-ID` header.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reuse client-provided request ID or generate a new one
        request_id = request.headers.get("x-request-id")
        if not request_id:
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
