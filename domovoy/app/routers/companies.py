"""Справочник управляющих компаний."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ManagementCompany
from app.schemas import CompanyOut
from app.services.addresses import normalize_house, normalize_street
from app.services.matching import find_company

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)) -> list[ManagementCompany]:
    return list(db.execute(select(ManagementCompany).order_by(ManagementCompany.name)).scalars().all())


@router.get("/by-address", response_model=CompanyOut)
def company_by_address(street: str, house: str, db: Session = Depends(get_db)) -> ManagementCompany:
    """Какая УК обслуживает дом. Нужна боту перед отправкой обращения."""
    company = find_company(db, normalize_street(street), normalize_house(house))
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Для этого адреса управляющая компания не найдена")
    return company
