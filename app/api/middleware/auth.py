"""
app/api/middleware/auth.py
Bearer token authentication middleware.

All routes except /health and /docs require Authorization: Bearer <API_SECRET_KEY>.
Returns 401 on missing token, 403 on invalid token.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings

EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header missing or malformed"},
            )

        token = auth_header.removeprefix("Bearer ").strip()
        if token != settings.api_secret_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key"},
            )

        return await call_next(request)
