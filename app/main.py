"""FastAPI приложение «Домовой».

Здесь собирается всё: роутеры (пользователи, адреса, отключения,
обращения), обработка ошибок и автодокументация /docs. Сами эндпоинты
живут в app/routers/, схемы запросов и ответов — в app/schemas.py.

Запуск:

    uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.db import init_db
from app.errors import ConflictError, DomovoyError, NotFoundError
from app.routers import addresses, appeals, outages, users

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

DESCRIPTION = """
API сервиса «Домовой»: через него работают бот в MAX и сайт.

* **Пользователи** — регистрация жильца, его адреса и настройки уведомлений.
* **Отключения** — список и фильтр по адресу: `GET /outages?city=Новосибирск&street=Ленина&house_number=11`.
* **Обращения** — приём обращения жильца и его статус.

Ошибки отдаются одинаково: `404` — записи нет, `409` — такая уже есть,
`422` — не прошла проверка полей, в `errors` перечислены сами поля.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    # схема БД применяется при старте, чтобы API поднималось на пустой базе
    init_db()
    yield


app = FastAPI(
    title="Домовой API",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    contact={"name": "Домовой"},
)

app.include_router(users.router)
app.include_router(addresses.router)
app.include_router(outages.router)
app.include_router(appeals.router)


@app.get("/health", tags="служебное", summary="Проверка, что API живой")
def health() -> dict[str, str]:
    """Отвечает, пока API работает: без него не запустится и бот."""
    return {"status": "ok"}


@app.exception_handler(NotFoundError)
async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    # ограничение базы сработало там, где проверки приложения не хватило
    return JSONResponse(status_code=409, content={"detail": f"Такая запись уже есть: {exc.orig}"})


@app.exception_handler(DomovoyError)
async def domovoy_error_handler(_: Request, exc: DomovoyError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in item["loc"][1:]) or "запрос",
            "message": item["msg"],
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": "Проверьте заполнение полей", "errors": errors},
    )


# сайт лежит в web/ и отдаётся последним, чтобы не перехватывать API
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
