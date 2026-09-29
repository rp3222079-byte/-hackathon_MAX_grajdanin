"""Управляющие компании: только чтение, для бота и сайта."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import NotFoundError
from app.models import ManagementCompany
from app.schemas import CompanyOut

router = APIRouter(prefix="/companies", tags=["управляющие компании"])


@router.get("/{company_id}", response_model=CompanyOut, summary="Управляющая компания по id")
def get_company(company_id: int, db: Session = Depends(get_db)) -> ManagementCompany:
    """Отдаёт компанию: нужна боту, чтобы отправить письмо по обращению."""
    company = db.get(ManagementCompany, company_id)
    if company is None:
        raise NotFoundError(f"Компания {company_id} не найдена")
    return company
