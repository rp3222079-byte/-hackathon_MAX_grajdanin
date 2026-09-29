"""Справочник управляющих компаний: только чтение, для бота."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import ManagementCompany
from app.schemas import CompanyOut
from app.services.addresses import normalize_corpus
from app.services.directory import find_company, find_streets, list_cities

router = APIRouter(prefix="/companies", tags=["управляющие компании"])


@router.get("/cities", response_model=list[str], summary="Города со справочником УК")
def get_cities(db: Session = Depends(get_db)) -> list[str]:
    """Бот предлагает их кнопками на первом шаге ввода адреса."""
    return list_cities(db)


@router.get("/streets", response_model=list[str], summary="Подсказка улиц")
def get_streets(
    city: str = Query(min_length=1, description="Город, например «Новосибирск»."),
    q: str = Query(min_length=1, description="Улица, как её ввёл жилец."),
    db: Session = Depends(get_db),
) -> list[str]:
    """Точное совпадение — одна улица; иначе до шести похожих, лучшие первыми.

    Пустой список — такой улицы в справочнике нет.
    """
    return find_streets(db, city, q)


@router.get("/lookup", response_model=CompanyOut, summary="УК по адресу дома")
def lookup_company(
    city: str = Query(min_length=1),
    street: str = Query(min_length=1),
    house_number: int = Query(ge=1),
    house_corpus: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ManagementCompany:
    """Какая УК обслуживает дом. 404 — дома в справочнике нет."""
    company = find_company(db, city, street, house_number, normalize_corpus(house_corpus))
    if company is None:
        raise NotFoundError("Дом не найден в справочнике управляющих компаний")
    return company


@router.get("/{company_id}", response_model=CompanyOut, summary="Управляющая компания по id")
def get_company(company_id: int, db: Session = Depends(get_db)) -> ManagementCompany:
    """Отдаёт компанию: нужна боту, чтобы отправить письмо по обращению."""
    company = db.get(ManagementCompany, company_id)
    if company is None:
        raise NotFoundError(f"Компания {company_id} не найдена")
    return company
