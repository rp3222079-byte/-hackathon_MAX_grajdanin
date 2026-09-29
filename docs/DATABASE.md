# Схема базы данных

Модели — `app/models.py`, подключение — `app/db.py`, миграции — `app/migrations.py`.
Локально база SQLite (`domovoy.db`), в Docker — PostgreSQL; строка подключения
приходит из переменной `DATABASE_URL` (`app/config.py`).

Схема состоит из пяти основных сущностей — пользователи, адреса, управляющие
компании, отключения и обращения — и трёх вспомогательных таблиц: дома УК,
отметки об отправленных уведомлениях и служебная `schema_migrations`.

## Связи

```
users ──< addresses >── appeals >── management_companies ──< company_houses
             │              │
             └──────────────┘        (appeals.address_id — адрес обращения)

users ──< outage_notifications >── outages
```

| Таблица | О чём |
|---|---|
| `users` | жилец: аккаунт в мессенджере и настройки уведомлений |
| `addresses` | адреса жильца, по ним приходят уведомления |
| `management_companies` | управляющие компании, получатели обращений |
| `company_houses` | дома, закреплённые за управляющими компаниями |
| `outages` | отключения воды и света (в MVP — демо-данные `app/seed.py`) |
| `outage_notifications` | отметки «жилец уже уведомлён», защита от повторной рассылки |
| `appeals` | обращения жильцов в управляющую компанию |

## Таблицы

### users

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `max_user_id` | str(64) | unique, index | `user_id` жильца в MAX: по нему бот отправляет сообщения (до миграции 4 — `telegram_id`) |
| `notify_outages` | bool | default `true` | общий выключатель уведомлений |
| `notify_water` | bool | default `true` | |
| `notify_electricity` | bool | default `true` | |
| `created_at` | datetime | server default `now()` | |
| `updated_at` | datetime | server default `now()`, on update | |

### addresses

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `user_id` | int | FK `users.id`, index, on delete CASCADE | чей адрес |
| `city` | str(120) | | |
| `street` | str(200) | | как ввёл жилец; нормализуется при поиске отключений |
| `house_number` | int | | номер дома |
| `house_corpus` | str(16) | null | корпус: `к2` |
| `flat` | int | null | квартира |
| `is_primary` | bool | default `false` | адрес по умолчанию |
| `created_at` | datetime | server default `now()` | |

Индексы: `ix_addresses_user_id`, `ix_addresses_place (city, street, house_number)` —
по нему ищут затронутых жителей. Уникальный индекс `uq_addresses_user_place`
не даёт добавить жильцу один и тот же дом дважды; корпус входит в него через
`coalesce(house_corpus, '')`, иначе пустые корпуса не сравнивались бы между собой.

### management_companies

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `name` | str(255) | | |
| `email` | str(255) | index | куда уходит письмо с обращением |
| `phone` | str(64) | null | |
| `website` | str(255) | null | |
| `city` | str(120) | index | |
| `created_at` | datetime | server default `now()` | |

Уникальное ограничение `uq_companies_name_city (name, city)`: одна и та же
компания в городе не заводится дважды.

### company_houses

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `company_id` | int | FK `management_companies.id`, index, on delete CASCADE | чей дом |
| `city` | str(120) | | |
| `street` | str(200) | | |
| `house_number` | int | | |
| `house_corpus` | str(16) | null | |

Уникальный индекс `uq_company_houses_place` — как и у адресов, корпус входит
через `coalesce(house_corpus, '')`. По этой таблице определяется, кому
уходит обращение.

### outages

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `utility` | str(32) | index | `water` или `electricity`, константы `UTILITY_TYPES` в `app/models.py` |
| `city` | str(120) | index | |
| `street` | str(200) | | как в источнике |
| `houses_raw` | str(500) | | список домов строкой: `1-15, 12к2` |
| `starts_at` | datetime | index | начало |
| `ends_at` | datetime | null | окончание, может быть неизвестно |
| `source` | str(255) | | адрес страницы-источника |
| `reason` | text | null | причина |
| `created_at` | datetime | server default `now()` | |

Уникальное ограничение `uq_outages_source_row (utility, city, street, houses_raw,
starts_at)` — та же строка источника повторно в базу не попадает, поэтому
парсер можно гонять часто.

Список домов хранится строкой намеренно: разбирает его
`parse_house_list` из `app/services/addresses.py`, а искать по нему нужно
только при рассылке уведомлений.

### outage_notifications

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `user_id` | int | FK `users.id`, index, on delete CASCADE | кому отправили |
| `outage_id` | int | FK `outages.id`, index, on delete CASCADE | что отправили |
| `sent_at` | datetime | server default `now()` | |

Уникальное ограничение `uq_notifications_user_outage (user_id, outage_id)`:
одно и то же уведомление жильцу не придёт дважды.

### appeals

| Колонка | Тип | Ограничения | Про смысл |
|---|---|---|---|
| `id` | int | primary key | |
| `number` | str(32) | unique, index | номер для жильца и письма: `DM-00001` |
| `user_id` | int | FK `users.id`, index, on delete SET NULL | пусто, если обращение пришло без аккаунта |
| `company_id` | int | FK `management_companies.id`, index, on delete SET NULL | пусто, если для дома не нашлось УК |
| `address_id` | int | FK `addresses.id`, index, on delete SET NULL | |
| `address_text` | str(400) | | адрес текстом: обращение может прийти и без заведённого адреса |
| `subject` | str(200) | | тема |
| `text` | text | | текст обращения |
| `photo_path` | str(400) | null | сколько фото приложено к письму (сами фото хранятся только в письме) |
| `contact` | str(255) | null | контакт жильца для УК — только с его согласия |
| `uk_comment` | text | null | комментарий УК со страницы обращения, жилец видит его в боте |
| `notified_status` | str(32) | null | последний статус, о котором бот сообщил жильцу; расхождение со `status` — повод для уведомления |
| `status` | str(32) | index, default `new` | `new` → `sent` / `failed` (ставит бот) → `in_progress` → `resolved` (ставит УК), константы `APPEAL_STATUSES` |
| `created_at` | datetime | default — местное время `TIMEZONE` | |
| `updated_at` | datetime | server default `now()`, on update | |
| `sent_at` | datetime | null | когда ушло письмо в УК |
| `resolved_at` | datetime | null | когда УК ответила |

### schema_migrations

Служебная таблица: `version` (primary key), `name`, `applied_at`. По ней
миграции видно, что уже применено.

## Миграции

```bash
python -m app.migrations            # применить недостающие
python -m app.migrations --status   # показать, что уже применено
```

Миграция — функция с номером и названием; применяются по возрастанию номера,
каждая в своей транзакции:

```python
@migration(2, "add_appeals_photo")
def add_appeals_photo(conn: Connection) -> None:
    conn.execute(text("ALTER TABLE appeals ADD COLUMN photo_size INTEGER"))
```

`Base.metadata.create_all` создаёт только новые таблицы: изменили колонку —
нужна миграция, а не удаление базы.

| № | Название | Что делает |
|---|---|---|
| 1 | `initial_schema` | таблицы по `app/models.py` |
| 2 | `add_notify_hours_before` | `users.notify_hours_before` |
| 3 | `clear_fake_uk_emails` | убирает выдуманные адреса `@gis.jkh` |
| 4 | `rename_telegram_id` | `users.telegram_id` → `users.max_user_id` |
| 5 | `appeal_contact_and_status_notice` | `appeals.contact`, `uk_comment`, `notified_status`; старым обращениям `notified_status = status`, чтобы не было лишних уведомлений |

## Что упрощено

- Значения, которые повторяются в коде (типы отключений, статусы обращений),
  лежат константами в `app/models.py`, а не в справочниках: их набор можно
  расширить без правки схемы.
- Логина и пароля у жильца нет: он опознаётся по `user_id` в MAX.
- Уличные и домовые ключи для сопоставления не хранятся, улица нормализуется
  на лету (`app/services/addresses.py`, `app/services/matching.py`).
- Полноценные миграции Alembic — следующий шаг после хакатона.
