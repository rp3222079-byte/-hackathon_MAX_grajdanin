"""Справочник УК: города, улицы и поиск компании по дому.

Сравнение идёт на Python, а не в SQL: lower() в SQLite не понимает
кириллицу, а улицы в справочнике и у жильца пишутся по-разному
(«улица Ленина» и «ул. Ленина»).
"""
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyHouse, ManagementCompany
from app.services.addresses import normalize_corpus, normalize_street
from app.services.matching import normalize_city

STREET_SUGGESTIONS = 6
# Насколько похожей должна быть улица, чтобы попасть в подсказки,
# и насколько подсказка может уступать лучшей
STREET_SIMILARITY = 0.7
STREET_SPREAD = 0.1


def list_cities(db: Session) -> list[str]:
    """Города, для которых есть справочник УК."""
    return sorted(set(db.scalars(select(CompanyHouse.city).distinct())))


def canonical_city(db: Session, city: str) -> str | None:
    """Город так, как он записан в справочнике: «новосибирск» → «Новосибирск»."""
    wanted = normalize_city(city)
    for known in list_cities(db):
        if normalize_city(known) == wanted:
            return known
    return None


def _city_streets(db: Session, city: str) -> list[str]:
    known = canonical_city(db, city)
    if known is None:
        return []
    return sorted(
        set(db.scalars(select(CompanyHouse.street).where(CompanyHouse.city == known).distinct()))
    )


def find_streets(db: Session, city: str, query: str) -> list[str]:
    """Улицы города, похожие на введённую жильцом, лучшие — первыми.

    Точное совпадение после нормализации — единственный ответ.
    Иначе — улицы, которые содержат введённое, и близкие по написанию.
    """
    wanted = normalize_street(query)
    if not wanted:
        return []
    streets = _city_streets(db, city)
    exact = [street for street in streets if normalize_street(street) == wanted]
    if exact:
        return exact[:1]

    scored = []
    for street in streets:
        name = normalize_street(street)
        if len(wanted) >= 3 and wanted in name:
            score = 0.95  # «Карла» → «Карла Маркса»
        elif len(name) >= 4 and name in wanted:
            score = 0.9  # «Ленина пр» → «Ленина»
        else:
            score = SequenceMatcher(None, wanted, name).ratio()
        if score >= STREET_SIMILARITY:
            scored.append((score, street))
    if not scored:
        return []
    # только лучшие варианты: «Ленена» → «Ленина», без «Лесной» и «Солнечной»
    best = max(score for score, _ in scored)
    close = sorted(
        ((-score, street) for score, street in scored if score >= best - STREET_SPREAD),
    )
    return [street for _, street in close[:STREET_SUGGESTIONS]]


def find_company(
    db: Session,
    city: str,
    street: str,
    house_number: int,
    house_corpus: str | None = None,
) -> ManagementCompany | None:
    """УК, которой закреплён дом; None — если дома в справочнике нет.

    Сначала ищется точное совпадение корпуса. Если у жильца корпус не
    указан, а в справочнике дом записан с корпусом (или наоборот),
    берётся тот же номер дома на той же улице: такие дома почти всегда
    обслуживает одна УК.
    """
    houses = db.scalars(select(CompanyHouse).where(CompanyHouse.house_number == house_number)).all()
    wanted_city = normalize_city(city)
    wanted_street = normalize_street(street)
    wanted_corpus = normalize_corpus(house_corpus)

    same_house = [
        house
        for house in houses
        if normalize_city(house.city) == wanted_city
        and normalize_street(house.street) == wanted_street
    ]
    exact = [house for house in same_house if normalize_corpus(house.house_corpus) == wanted_corpus]
    # «12» и «12к2» считаем одним домом, а «12к2» и «12к3» — разными
    similar = [house for house in same_house if not house.house_corpus or not wanted_corpus]
    chosen = (exact or similar or [None])[0]
    if chosen is None:
        return None
    return db.get(ManagementCompany, chosen.company_id)
