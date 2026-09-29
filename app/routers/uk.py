"""Страница обращения для управляющей компании.

Ссылка приходит в письме с обращением. Сотрудник УК открывает её без
регистрации, отмечает «В работе» или «Решено» и при желании пишет
комментарий — бот сообщит об этом жильцу в MAX.

Доступ проверяется подписью в ссылке (app/security.py): подобрать
ссылку на чужое обращение нельзя. Статус меняется только кнопкой
(POST), поэтому почтовые сканеры, открывающие ссылки из писем,
ничего не изменят.
"""
from html import escape

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import APPEAL_STATUS_IN_PROGRESS, APPEAL_STATUS_RESOLVED, Appeal
from app.security import check_appeal_signature
from app.services.statuses import change_status

router = APIRouter(prefix="/uk", tags=["страница УК"], include_in_schema=False)

STATUS_LABELS = {
    "new": "создано",
    "sent": "отправлено в УК",
    "in_progress": "в работе",
    "resolved": "решено",
    "failed": "не отправлено",
}
UK_STATUSES = (APPEAL_STATUS_IN_PROGRESS, APPEAL_STATUS_RESOLVED)

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#1c2733}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}
.card{{background:#fff;border:1px solid #dde3ec;border-radius:12px;padding:20px;margin-bottom:16px}}
h1{{font-size:22px;margin:0 0 4px}} .muted{{color:#66748a;font-size:14px}}
dl{{display:grid;grid-template-columns:140px 1fr;gap:8px 12px;margin:16px 0 0}}
dt{{color:#66748a}} dd{{margin:0}}
.text{{white-space:pre-wrap;background:#f4f6f9;border-radius:8px;padding:12px;margin-top:12px}}
.status{{display:inline-block;padding:3px 10px;border-radius:999px;background:#e3f3f5;color:#1a7f8e;font-weight:bold}}
label{{display:block;margin:10px 0}} textarea{{width:100%;box-sizing:border-box;min-height:90px;padding:8px;border:1px solid #cbd3de;border-radius:8px;font:inherit}}
button{{background:#1a7f8e;color:#fff;border:0;border-radius:8px;padding:12px 18px;font-size:16px;cursor:pointer}}
.ok{{background:#e6f4ea;border-color:#b7dfc3}} .err{{background:#fbe7e5;border-color:#f2c9c5}}
</style></head><body><main>{body}</main></body></html>"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=escape(title), body=body), status_code=status_code)


def _forbidden() -> HTMLResponse:
    return _page(
        "Ссылка недействительна",
        '<div class="card err"><h1>Ссылка недействительна</h1>'
        '<p>Откройте обращение по ссылке из письма целиком.</p></div>',
        403,
    )


def _find(db: Session, number: str) -> Appeal | None:
    return db.scalar(select(Appeal).where(Appeal.number == number))


def _appeal_card(appeal: Appeal) -> str:
    rows = [
        ("Адрес", appeal.address_text),
        ("Тема", appeal.subject),
        ("Контакт жильца", appeal.contact or "не указан"),
        ("Создано", appeal.created_at.strftime("%d.%m.%Y %H:%M") if appeal.created_at else "—"),
    ]
    if appeal.uk_comment:
        rows.append(("Ваш комментарий", appeal.uk_comment))
    details = "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in rows)
    return (
        f'<div class="card"><h1>Обращение №{escape(appeal.number)}</h1>'
        f'<span class="status">{escape(STATUS_LABELS.get(appeal.status, appeal.status))}</span>'
        f"<dl>{details}</dl>"
        f'<div class="text">{escape(appeal.text)}</div></div>'
    )


def _form(appeal: Appeal, signature: str) -> str:
    options = "".join(
        f'<label><input type="radio" name="status" value="{value}"'
        f'{" checked" if index == 0 else ""}> {STATUS_LABELS[value].capitalize()}</label>'
        for index, value in enumerate(UK_STATUSES)
    )
    return (
        f'<form class="card" method="post" action="/uk/appeals/{escape(appeal.number)}">'
        f'<input type="hidden" name="sig" value="{escape(signature)}">'
        f"<h1>Ответ жильцу</h1>{options}"
        '<label>Комментарий (увидит жилец)<textarea name="comment" maxlength="2000" '
        'placeholder="Например: мастер придёт завтра с 10 до 12"></textarea></label>'
        "<button type=\"submit\">Сохранить и уведомить жильца</button></form>"
    )


@router.get("/appeals/{number}", response_class=HTMLResponse)
def show_appeal(number: str, sig: str | None = Query(default=None), db: Session = Depends(get_db)):
    appeal = _find(db, number)
    if appeal is None or not check_appeal_signature(number, sig):
        return _forbidden()
    return _page(f"Обращение №{number}", _appeal_card(appeal) + _form(appeal, sig))


@router.post("/appeals/{number}", response_class=HTMLResponse)
def update_appeal(
    number: str,
    sig: str = Form(...),
    status: str = Form(...),
    comment: str = Form(default="", max_length=2000),
    db: Session = Depends(get_db),
):
    appeal = _find(db, number)
    if appeal is None or not check_appeal_signature(number, sig):
        return _forbidden()
    if status not in UK_STATUSES:
        return _page("Неизвестный статус", '<div class="card err"><h1>Выберите статус</h1></div>', 422)

    change_status(db, appeal, status, comment)
    notice = (
        f'<div class="card ok"><h1>Готово</h1><p>Статус «{escape(STATUS_LABELS[status])}» сохранён. '
        "Жилец получит сообщение в MAX в течение минуты.</p></div>"
    )
    return _page(f"Обращение №{number}", notice + _appeal_card(appeal) + _form(appeal, sig))
