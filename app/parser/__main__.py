"""Парсер управляющих компаний из открытых данных ГИС ЖКХ.

    python -m app.parser --city Новосибирск --out data/nsk
    python -m app.parser --city Новосибирск --out data/nsk --load
    python -m app.parser --load data/companies.csv

Порядок работы: скачиваются две выгрузки dom.gosuslugi.ru, дома
сопоставляются с организациями по ОГРН, результат пишется в csv и
json, а с флагом --load ещё и загружается в базу.
"""
import argparse
import logging
from pathlib import Path

from app.parser import downloader, export
from app.parser.companies import build_directory
from app.parser.loader import load_file

logger = logging.getLogger("domovoy.parser")

# Реестр поставщиков информации и выгрузка объектов жилищного фонда
PROVIDERS_PATH = "/ppa/api/rest/services/ppa/export/public/information/providers"
FILE_STORE_PATH = "/filestore/publicDownloadServlet"


def fetch_providers(cache_dir: Path, *, force: bool = False) -> Path:
    """Скачивает реестр поставщиков информации в xlsx."""
    destination = cache_dir / "providers.xlsx"
    if destination.exists() and not force:
        return destination
    meta = downloader.get_json(PROVIDERS_PATH)
    if not isinstance(meta, dict) or not meta.get("fileGuid"):
        raise downloader.SourceError(f"реестр поставщиков не отдан: {meta}")
    url = f"{downloader.BASE_URL}{FILE_STORE_PATH}?context=ppa&uid={meta['fileGuid']}"
    return downloader.download_file(url, destination)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Парсер УК из открытых данных ГИС ЖКХ")
    parser.add_argument("--city", default="Новосибирск", help="Город, для которого нужен справочник")
    parser.add_argument("--out", type=Path, help="Каталог для csv и json со справочником")
    parser.add_argument("--cache", type=Path, default=Path("parser_cache"), help="Каталог для выгрузок")
    parser.add_argument(
        "--load",
        nargs="?",
        const="",
        type=str,
        metavar="ФАЙЛ",
        help="Загрузить в базу: файл или, если не указан, последний результат парсинга",
    )
    parser.add_argument("--force", action="store_true", help="Скачать выгрузки заново")
    arguments = parser.parse_args()

    if arguments.out is not None:
        parse_city(arguments.city, arguments.out, arguments.cache, force=arguments.force)
    if arguments.load is not None:
        source = Path(arguments.load) if arguments.load else _last_result(arguments.out)
        if not source or not source.is_file():
            logger.error("Файл для загрузки не найден: %s", source)
            raise SystemExit(1)
        from app.db import SessionLocal, init_db

        init_db()
        db = SessionLocal()
        try:
            result = load_file(db, source)
            logger.info("Загружено компаний: %s, домов: %s", result.companies, result.houses)
        finally:
            db.close()


def parse_city(city: str, out: Path, cache: Path, *, force: bool = False) -> None:
    """Собирает справочник города и пишет его в csv и json."""
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    logger.info("Качаю реестр поставщиков информации")
    providers = fetch_providers(cache, force=force)
    logger.info("Качаю сведения об объектах жилищного фонда")
    houses = downloader.download_ozhf_csv(cache, force=force, region=city)

    logger.info("Собираю справочник по городу %s", city)
    directory = build_directory(providers, houses, city)
    total_houses = sum(company.houses_count for company in directory.values())
    logger.info("Компаний: %s, домов: %s", len(directory), total_houses)

    csv_path = out / f"{downloader.slug(city)}.csv"
    json_path = out / f"{downloader.slug(city)}.json"
    rows = export.write_csv(directory, csv_path)
    companies = export.write_json(directory, json_path)
    logger.info("Записано %s строк в %s и %s компаний в %s", rows, csv_path, companies, json_path)


def _last_result(out: Path | None) -> Path | None:
    if out is None:
        return None
    candidates = sorted(out.glob("*.json"))
    return candidates[-1] if candidates else None


if __name__ == "__main__":
    main()
