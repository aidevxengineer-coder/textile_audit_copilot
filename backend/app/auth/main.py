from __future__ import annotations

from urllib.parse import urlparse
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.config import get_settings
from app.db.session import create_db_and_seed


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_seed()
    yield


def _allowed_origins() -> list[str]:
    configured = {str(settings.frontend_url).rstrip("/"), str(settings.public_app_url).rstrip("/")}
    variants = set(configured)
    for origin in configured:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.port:
            continue
        if parsed.hostname == "localhost":
            variants.add(f"{parsed.scheme}://127.0.0.1:{parsed.port}")
        if parsed.hostname == "127.0.0.1":
            variants.add(f"{parsed.scheme}://localhost:{parsed.port}")
    return sorted(variants)


app = FastAPI(title=f"{settings.app_name} Authentication Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "authentication"}


app.include_router(auth_router)
