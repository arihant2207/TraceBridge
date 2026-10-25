"""FastAPI application entry point for TraceBridge."""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.db.database import init_db
from app.engine.models import SchemaValidationError

from contextlib import asynccontextmanager

logger = logging.getLogger("tracebridge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema is initialized on startup."""
    init_db()
    yield


app = FastAPI(
    title="TraceBridge",
    description="Deterministic Engineering-Evidence Validation Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)


# =============================================================================
# Custom Exception Handlers for Unified Error Envelope
# {"error": {"code": str, "message": str, "details": list[str]}}
# =============================================================================
@app.exception_handler(SchemaValidationError)
async def schema_validation_error_handler(
    request: Request, exc: SchemaValidationError
) -> JSONResponse:
    """Handle SCH-xxx schema validation errors with HTTP 422."""
    codes = [e.code for e in exc.errors]
    primary_code = codes[0] if codes else "SCHEMA_ERROR"
    details = [f"{e.code}: {e.message}" for e in exc.errors]
    for e in exc.errors:
        for d in e.details:
            details.append(f"{e.code} detail: {d}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": primary_code,
                "message": f"Schema validation failed: {', '.join(codes)}",
                "details": details,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handle HTTP exceptions conforming to the error envelope."""
    status_code_map = {
        status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "UNPROCESSABLE_ENTITY",
        status.HTTP_409_CONFLICT: "CONFLICT",
    }
    code = status_code_map.get(exc.status_code, f"HTTP_{exc.status_code}")

    if isinstance(exc.detail, dict) and "code" in exc.detail:
        error_content = exc.detail
    elif isinstance(exc.detail, list):
        error_content = {
            "code": code,
            "message": "HTTP error occurred",
            "details": [str(d) for d in exc.detail],
        }
    else:
        error_content = {
            "code": code,
            "message": str(exc.detail),
            "details": [],
        }

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error_content},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI/Pydantic request validation errors."""
    details = [
        f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": "Invalid request parameters or payload",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Never expose raw server errors (HTTP 500 returns generic message)."""
    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred.",
                "details": [],
            }
        },
    )
