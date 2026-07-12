"""StarShield Lite — FastAPI application.

Launch:
  python main.py api
  starshield-api
  uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

Interactive docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from api.rate_limit import RateLimitMiddleware, rate_limit_status
from api.routers import debris, export, health, history, objects, passes, watchlist
from api.security import API_KEY_HEADER_NAME, auth_enabled, get_valid_keys
from config import API_KEY_REQUIRED, DB_PATH, __version__
from services.database import ensure_db
from services.object_index import get_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_db()
    except Exception:
        pass
    try:
        get_index()
    except Exception:
        pass
    if auth_enabled():
        n = len(get_valid_keys())
        print(
            f"[auth] API key required · {n} key(s) loaded · "
            f"header: {API_KEY_HEADER_NAME}"
        )
        if n == 0:
            print(
                "[auth] WARNING: no keys configured — "
                "protected routes will return 503 until you add keys "
                "(python main.py apikey --cmd generate)"
            )
    else:
        print("[auth] API key auth disabled (STARSHIELD_API_KEY_REQUIRED=0)")
    rl = rate_limit_status()
    if rl["enabled"]:
        print(
            f"[rate-limit] enabled · public={rl['public']} · "
            f"default={rl['default']} · heavy={rl['heavy']}"
        )
    else:
        print("[rate-limit] disabled (STARSHIELD_API_RATE_LIMIT=0)")
    yield


_API_DESCRIPTION = """
Personal space domain awareness API.

Core capabilities: multi-catalog object search (including optional debris),
pass prediction with quality scoring, conjunction watchlists, debris
conjunction scans, SQLite history, and file export.

**Authentication**

When `STARSHIELD_API_KEY_REQUIRED=1`, protected endpoints require header:

```
X-API-Key: <your-key>
```

| Access | Endpoints |
|--------|-----------|
| **Public** | `/health`, `/objects/*`, `GET /watchlist`, `GET /debris/*` (read) |
| **Protected** | `/passes`, `POST /watchlist/scan`, `POST /debris/fetch`, `POST /debris/scan`, `/history/*`, `/export/*` |

**Rate limiting**

When `STARSHIELD_API_RATE_LIMIT=1` (default), clients are limited by IP.
Heavy routes (`/passes`, `/watchlist/scan`, `/export`) use a stricter quota.
Exceeded limits return **HTTP 429**.

Services in `services/` are the source of truth; this layer is a thin HTTP façade.
"""

app = FastAPI(
    title="StarShield Lite API",
    description=_API_DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    contact={"name": "StarShield Lite"},
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "ApiKeyAuth"
    ] = {
        "type": "apiKey",
        "in": "header",
        "name": API_KEY_HEADER_NAME,
        "description": "API key for protected endpoints",
    }
    if API_KEY_REQUIRED:
        schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", API_KEY_HEADER_NAME],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "code": "internal_error"},
    )


app.include_router(health.router)
app.include_router(objects.router)
app.include_router(passes.router)
app.include_router(watchlist.router)
app.include_router(debris.router)
app.include_router(history.router)
app.include_router(export.router)


def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Entrypoint used by ``python main.py api`` / ``starshield-api``."""
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def main():
    """Console script entry: ``starshield-api``."""
    from config import API_HOST, API_PORT

    run(host=API_HOST, port=API_PORT, reload=False)


if __name__ == "__main__":
    main()
