"""RFC 9457 problem responses (API_DESIGN.md section 1).

Validation errors never echo the submitted input back (it may contain a password or other
personal data); only the field location and a message are returned.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://mindmitra.example/problems/"
_TITLES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    422: "Unprocessable content",
    429: "Too many requests",
    500: "Internal server error",
    503: "Service unavailable",
}
_SLUGS = {
    401: "unauthorized",
    403: "forbidden",
    404: "not-found",
    409: "conflict",
    422: "validation-error",
    429: "rate-limited",
    503: "unavailable",
}


def problem(
    request: Request,
    status: int,
    detail: str,
    *,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + _SLUGS.get(status, "error"),
        "title": _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(
        body, status_code=status, headers=headers, media_type="application/problem+json"
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else _TITLES.get(exc.status_code, "")
        return problem(request, exc.status_code, detail, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        return problem(request, 422, "The request is not valid.", errors=errors)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (or bound SQL parameters) to the client.
        return problem(request, 500, "Something went wrong. Please try again.")
