"""REST API сервиса «Домовой» и отдача статического сайта."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import appeals, companies, outages, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Домовой API",
    description="Отключения воды и электричества и обращения жильцов в управляющие компании.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # для хакатона; в проде укажите домен сайта
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(outages.router)
app.include_router(appeals.router)
app.include_router(companies.router)


@app.get("/api/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/appeal", include_in_schema=False)
    def appeal_page() -> FileResponse:
        return FileResponse(WEB_DIR / "appeal.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(WEB_DIR / "admin.html")
