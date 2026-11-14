# Локальный стенд разработки (этап 2, шаг 1)

Стенд поднимает три сервиса через Docker Compose:

| Сервис | Образ | Порт (только localhost) | Назначение |
|---|---|---|---|
| `db` | `postgis/postgis:16-3.5` | 5432 | PostgreSQL + PostGIS, таблицы `restrictions` и `restriction_events` |
| `api` | собирается из `api/Dockerfile` (Node 22) | 8080 | HTTP API: `/health`, `/v1/restrictions`, `/v1/route` |
| `valhalla` | `ghcr.io/valhalla/valhalla-scripted:3.9.2` | 8002 | Маршрутизатор (профиль `truck`, ADR-0009). Только с профилем `routing` |

> **Прототип, не для навигации.** Каждый ответ `/v1/route` содержит блок `trucksil` с этим предупреждением. Отсутствие ограничения в базе не означает, что дорога подходит (ADR-0002).

## 1. Установка Docker (Ubuntu или WSL2)

**Ubuntu 22.04/24.04:**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"   # затем перелогиниться
docker compose version            # нужна Compose v2
```

**WSL2 (Windows):** проще всего установить Docker Desktop и включить интеграцию с вашим дистрибутивом (Settings → Resources → WSL integration). Репозиторий держите внутри файловой системы Linux (`~/TrucksIL`), а не в `/mnt/c/...` — иначе тома и сборка тайлов будут очень медленными. Для Valhalla выделите WSL не меньше 8 ГБ памяти (`%UserProfile%\.wslconfig`, параметр `memory=8GB`).

## 2. Настройка

```bash
cd ~/TrucksIL
cp .env.example .env
# откройте .env и замените POSTGRES_PASSWORD
```

`.env` в git не попадает (`.gitignore`); в репозитории лежит только `.env.example`.

## 3. Запуск без маршрутизации (БД + API)

Данные OSM не нужны.

```bash
docker compose up -d --build
docker compose ps                         # db должен быть healthy
curl -s localhost:8080/health
# {"status":"degraded","db":"ok","valhalla":"down"}   <- valhalla не запущен, это ожидаемо
curl -s 'localhost:8080/v1/restrictions?bbox=34.2,29.4,35.9,33.4'
# {"type":"FeatureCollection","features":[]}
```

По умолчанию `VALHALLA_URL=http://valhalla:8002` (задано в `docker-compose.yml`), поэтому без профиля `routing` `/health` показывает `"valhalla":"down"` (код 503), а `POST /v1/route` отвечает `503` «Valhalla unreachable». API при этом не падает.

Если маршрутизация не нужна намеренно, раскомментируйте в `.env` пустое значение `VALHALLA_URL=` — тогда `/health` → `{"status":"ok","db":"ok","valhalla":"disabled"}`, а `/v1/route` → `503` «routing disabled».

Миграции из `db/migrations/*.sql` применяются автоматически **только при первом запуске** (когда том `db-data` пуст). Чтобы пересоздать базу с нуля: `docker compose down -v` (удалит все данные БД).

## 4. Запуск с маршрутизацией (Valhalla)

1. Скачайте выгрузку OSM вручную (≈ 100–150 МБ) с Geofabrik: страница <https://download.geofabrik.de/asia/israel-and-palestine.html>, файл `israel-and-palestine-latest.osm.pbf`. Данные OSM — под лицензией ODbL, укажите атрибуцию «© OpenStreetMap contributors».
2. Положите файл в `data/osm/`:
   ```bash
   mv ~/Downloads/israel-and-palestine-latest.osm.pbf data/osm/
   ```
   Папка `data/osm/` в git игнорируется (кроме `.gitkeep`). Сам стенд ничего не скачивает.
3. Править `.env` не нужно: `VALHALLA_URL` по умолчанию указывает на сервис `valhalla`. (Если в старом `.env` осталась строка `VALHALLA_URL=` с пустым значением — удалите её, иначе маршрутизация будет выключена.)
4. Запустите:
   ```bash
   docker compose --profile routing up -d --build
   docker compose logs -f valhalla   # первая сборка тайлов: ~10–30 минут, 4–8 ГБ RAM
   ```
   Готовые тайлы сохраняются в `data/osm/` и при следующих запусках не пересобираются. Чтобы пересобрать после обновления `.pbf`, временно поставьте `force_rebuild: "True"` в `docker-compose.yml` или удалите сгенерированные файлы в `data/osm/` (кроме `.pbf`).
5. Проверьте: `curl -s localhost:8080/health` → `"valhalla":"ok"`.

### Пример запроса маршрута

Профиль вымышленный (не реальная машина); формат — `data/vehicle-profile.schema.json`. Координаты — `[долгота, широта]`.

```bash
curl -s -X POST localhost:8080/v1/route \
  -H 'content-type: application/json' \
  -d '{
    "from": [34.7818, 32.0853],
    "to":   [35.2137, 31.7683],
    "vehicle": {
      "profileName": "Демо-тягач (вымышленный)",
      "heightM": 4.0,
      "widthM": 2.55,
      "lengthM": 16.5,
      "grossWeightT": 40,
      "axleLoadT": 11.5
    }
  }'
```

Ответ — ответ Valhalla `/route` (поле `trip`) плюс блок `trucksil`:

```json
"trucksil": {
  "disclaimer": "prototype, not for navigation",
  "avoided": [{"id": "...", "restrictionType": "max_height", "value": 3.5, "unit": "m", "status": "unverified", "valueSource": "posted_sign", "reason": "heightM 4 > limit 3.5 m"}],
  "onRoute": [{"id": "...", "restrictionType": "max_height", "value": 4.6, "unit": "m", "status": "verified", "valueSource": "posted_sign"}],
  "coverage": {"verifiedOnRoute": 1, "unverifiedOnRoute": 0, "note": "Absence of restrictions in TrucksIL data does not mean the route is safe"},
  "unverifiedCoverage": "unknown",
  "reroutes": 1
}
```

Как применяются собственные ограничения TrucksIL (таблица `restrictions`):

1. Valhalla строит маршрут; API декодирует `trip.legs[].shape` (polyline6) и ищет в PostGIS ограничения в пределах 50 м от линии маршрута (`status <> 'expired'`, действующие сейчас по `time_windows`, время — Asia/Jerusalem).
2. Конфликт — ограничение, которое ТС нарушает: `max_height < heightM`, `max_width < widthM`, `max_length < lengthM`, `max_gross_weight < grossWeightT`, `max_axle_weight < axleLoadT` (если `axleLoadT` не указан — тоже конфликт), `truck_prohibited = true`, `hazmat_restriction = true` при наличии `hazmat`. Равенство не считается нарушением.
3. Конфликты объезжаются **независимо от статуса** (verified/unverified/disputed): объезд — всегда безопасное направление. Вокруг каждого конфликта строится многоугольник радиусом 20 м (`ST_Buffer` по geography) и передаётся в Valhalla как `exclude_polygons`; до 3 перестроений.
4. Если конфликт остаётся — `409` со списком `conflicts`; если Valhalla не находит маршрут в обход — `422`. Небезопасный маршрут как успешный не возвращается.
5. `onRoute` — ограничения на итоговом маршруте, которые ТС не нарушает (со статусом). Маршрут никогда не объявляется безопасным из-за непроверенных данных, а отсутствие записей ничего не гарантирует: `unverifiedCoverage` остаётся `"unknown"`.

`valueSource` и `value` показываются ровно как в базе (значение со знака — ADR-0004). Направление (`direction`) пока не учитывается: ограничение применяется в обе стороны (консервативно).

Сопоставление полей профиля с `costing_options.truck` Valhalla: `heightM→height`, `widthM→width`, `lengthM→length` (метры), `grossWeightT→weight`, `axleLoadT→axle_load` (тонны), наличие `hazmat→hazmat: true`.

Коды ответов: `400` — неверный JSON/координаты/профиль (с перечнем ошибок); `409` — маршрут всё ещё проходит через известное ограничение после 3 перестроений; `422` — маршрута в обход известных ограничений нет; `503` — Valhalla отключена/недоступна или БД недоступна (без проверки ограничений маршрут не отдаётся); `502` — Valhalla вернула 5xx или ответ без `shape`; ошибки 4xx Valhalla для первого запроса (например, «маршрут не найден») передаются как есть.

### Ручная проверка объезда (вымышленное ограничение)

Нужен запущенный стек с профилем `routing` и `npm ci` на хосте (для `pg`). Запись вымышленная, помечается `unverified` и источником `dev-test`; после проверки удалите её.

```bash
export DATABASE_URL="postgres://trucksil:$(grep ^POSTGRES_PASSWORD= .env | cut -d= -f2)@localhost:5432/trucksil"
REQ='{"from":[34.7818,32.0853],"to":[35.2137,31.7683],"vehicle":{"profileName":"Демо (вымышленный)","heightM":4.0,"widthM":2.55,"lengthM":16.5,"grossWeightT":40,"axleLoadT":11.5}}'

# 1. Исходный маршрут; точка из середины его линии (скрипт декодирует shape)
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" > /tmp/route.json
P=$(node scripts/dev_add_test_restriction.js pick < /tmp/route.json); echo "$P"   # например 35.0123,31.8456

# 2. Вымышленный мост 3.5 м в этой точке
node scripts/dev_add_test_restriction.js add ${P/,/ } 3.5

# 3. Тягач 4.0 м: ограничение должно попасть в trucksil.avoided, reroutes >= 1
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" | jq .trucksil
#   (можно сравнить trip.summary.length с /tmp/route.json — маршрут изменился)
#   С heightM 3.4 то же ограничение окажется в onRoute, а не в avoided.
#   Если объезда нет (точка на единственной дороге) — ответ 422 с conflicts.

# 4. Удалить запись
node scripts/dev_add_test_restriction.js delete
```

Без скрипта точку можно выбрать вручную: возьмите координату `[lon, lat]` из `trip.legs[0].shape` (polyline6, декодер — `api/src/polyline.js`) или кликните по дороге маршрута на карте OSM, и вставьте SQL:

```sql
INSERT INTO restrictions (id, road_segment_id, geometry, value_source, restriction_type, value_numeric, unit, status, source, observed_at)
VALUES ('dev-test-max-height', 'dev-test', ST_SetSRID(ST_MakePoint(<lon>, <lat>), 4326), 'posted_sign', 'max_height', 3.5, 'm',
        'unverified', '{"name":"dev-test","reference":"fictional"}', now());
-- после проверки:
DELETE FROM restrictions WHERE id = 'dev-test-max-height';
```

(`docker compose exec db psql -U trucksil -d trucksil`.) Точка должна лежать не дальше 50 м от линии маршрута.

## 5. Тесты

```bash
npm ci
npm test
```

Тесты API (`test/api/`) не требуют Docker: база и Valhalla подменяются заглушками. Эталонные маршруты — см. раздел 6.

## 6. Эталонные маршруты

Набор эталонных сценариев лежит в `test/scenarios/routes.json`. **Все ограничения в нём вымышленные** (источник `e2e-fictional`, id с префиксом `e2e-`) и к реальным дорогам отношения не имеют. Один и тот же файл используется дважды:

- `npm test` — быстрые тесты (`test/api/scenarios.test.js`) без Docker: настоящий HTTP-обработчик API, заглушка Valhalla (прямая линия; при `exclude_polygons` — объезд с отклонением ~5 км в середине) и хранилище ограничений в памяти с той же логикой, что SQL (50 м от линии, `expired` не применяется).
- `npm run test:e2e` — прогон на запущенном стенде (БД + API + настоящая Valhalla).

### Запуск на стенде

```bash
docker compose --profile routing up -d          # дождаться /health -> "status":"ok"
export DATABASE_URL=postgres://trucksil:<пароль из .env>@localhost:5432/trucksil
npm run test:e2e                                 # API_URL по умолчанию http://localhost:8080
E2E_ONLY=S02,S03 npm run test:e2e                # только выбранные сценарии
```

Для каждого сценария скрипт `scripts/e2e_routes.js`: строит базовый маршрут через API → вычисляет точки `{"onRouteFraction": f}` по его линии → записывает вымышленные ограничения → вызывает `POST /v1/route` → сверяет ожидания → **всегда** удаляет свои записи (в т. ч. после ошибки; перед запуском удаляются и остатки прерванного прогона). В конце печатается таблица PASS/FAIL/SKIP; при любом FAIL (или если в базе остались строки `e2e-*`) код выхода ненулевой. Сравниваются только засеянные `e2e-*` записи, так что реальные данные в базе не мешают (их число на базовом маршруте выводится в примечании).

### Что проверяет каждый сценарий

| ID | Маршрут | Проверка |
|----|---------|----------|
| S01 | Тель-Авив → Иерусалим | без ограничений: 200, `avoided` пуст, `reroutes` 0 |
| S02 | Тель-Авив → Иерусалим | мост 4,2 м, тягач 4,5 м → в `avoided`, `reroutes` ≥ 1 |
| S03 | Тель-Авив → Иерусалим | тот же мост, машина 3,9 м → в `onRoute`, без перестроения |
| S04 | Хайфа → Тель-Авив | `max_gross_weight` 20 т, 40 т → в `avoided` |
| S05 | Хайфа → Тель-Авив | `truck_prohibited` → в `avoided` |
| S06a | Беэр-Шева → Ашдод | `hazmat_restriction`, груз ADR 3 → в `avoided` |
| S06b | Беэр-Шева → Ашдод | то же без опасного груза → в `onRoute` |
| S07 | Тель-Авив → Иерусалим | высота 4,0 м = лимиту 4,0 м → не нарушение (`onRoute`) |
| S08 | Тель-Авив → Иерусалим | `verified` мост 5,0 м → `onRoute`, `coverage.verifiedOnRoute` ≥ 1 |
| S09 | Тель-Авив → Иерусалим | `expired` мост 3,0 м → игнорируется (нет ни в `avoided`, ни в `onRoute`) |
| S10 | Беэр-Шева → Ашдод | объезда нет → 422 с `conflicts`; **только заглушка** (`mockOnly`), в e2e пропускается |

На настоящей Valhalla число перестроений может быть больше 1 (рядом с исключённой точкой может оказаться параллельная проезжая часть), поэтому для объездов задан диапазон `minReroutes`…`maxReroutes` (1…3). Если точка `onRouteFraction` попала на участок без объезда, сценарий с объездом получит 422 — выберите другую долю.

### Как добавить сценарий

Добавьте объект в `scenarios` файла `test/scenarios/routes.json`:

```json
{
  "id": "S11", "description": "что проверяем",
  "from": "haifa", "to": "telAviv", "vehicle": "semi45",
  "restrictions": [{ "id": "s11-width", "type": "max_width", "value": 2.4, "unit": "m",
                     "status": "unverified", "valueSource": "posted_sign", "where": { "onRouteFraction": 0.3 } }],
  "expected": { "status": 200, "avoidedIds": ["s11-width"], "onRouteIds": [], "minReroutes": 1, "maxReroutes": 3 }
}
```

- `from`/`to` — имя из `places` или `[lon, lat]`; `vehicle` — имя из `vehicles` или полный профиль.
- `where` — `[lon, lat]` или `{"onRouteFraction": 0…1}` (доля длины базового маршрута); id указывается без `e2e-`, префикс добавляется автоматически.
- `expected`: `status` (200/409/422), `avoidedIds`, `onRouteIds`, `absentIds`, `conflictIds`, `minReroutes`/`maxReroutes`, `minVerifiedOnRoute`. Для сценариев, которые нельзя воспроизвести на настоящей Valhalla, — `"mockOnly": true` и `"mock": {"noDetour": true}`.
- Затем `npm test` (сценарий автоматически станет отдельным тестом) и `npm run test:e2e` на стенде.

## Известные ограничения

- Собственные ограничения TrucksIL применяются только после построения маршрута (проверка по линии + `exclude_polygons`), а не внутри графа Valhalla; базовый маршрут по-прежнему опирается на теги OSM, значения которых — лишь кандидаты (ADR-0006). Где в данных TrucksIL пробелы, узнать нельзя, поэтому `unverifiedCoverage` всегда `"unknown"`.
- `exclude_polygons` исключает все рёбра, пересекающие многоугольник (20 м), — в т. ч. соседнюю проезжую часть или пересекающую дорогу на развязке. Это консервативно, но может удлинить маршрут или дать `422`.
- `direction` ограничения не учитывается; временные окна проверяются на момент запроса, а не на время прохождения участка.
- Нет аутентификации, ограничения частоты запросов и HTTPS — стенд только для локальной машины (порты привязаны к `127.0.0.1`).
- `/v1/restrictions` возвращает не более 5000 объектов и только записи с геометрией.
- `/health` отвечает `503`, если БД или включённая Valhalla недоступна (в т. ч. при запуске без профиля `routing` и без `VALHALLA_URL=`); из-за этого Docker-healthcheck контейнера `api` тоже покажет `unhealthy`.
- Высоты рельефа (`build_elevation`) и пробки не используются.
- Сервис `valhalla` в этом окружении разработки ещё ни разу не запускался на реальном `.pbf`; первый запуск на вашей машине — фактически проверка конфигурации.

## Проверено на машине владельца (14.11.2026, Ubuntu 26.04 / WSL2, Docker Engine)
- `docker compose --profile routing up -d --build`: образы скачались, API собрался, Valhalla построила 82 тайла из выгрузки Geofabrik за ~17 с.
- `GET /health` → `{"status":"ok","db":"ok","valhalla":"ok"}` (после `VALHALLA_URL=http://valhalla:8002` в `.env` и `up -d --force-recreate api`).
- `POST /v1/route` Тель-Авив → Иерусалим с вымышленным профилем тягача: маршрут построен, `travel_type: "truck"`.
- Подсказка: если после правки `.env` compose пишет `Running`, а не `Recreated`, значит значение не изменилось — проверьте `grep -n VALHALLA_URL .env`.

## Проверка объезда на настоящей Valhalla (14.11.2026, машина владельца)
- Маршрут Тель-Авив → Иерусалим без ограничений: `avoided: []`, `reroutes: 0`.
- Вымышленный мост `max_height 3.5 m` (`unverified`, `posted_sign`) в точке 34.992966,31.826908 на маршруте.
- Тягач 4,0 м: ограничение в `avoided` с причиной `heightM 4 > limit 3.5 m`, `reroutes: 1` — маршрут перестроен в обход.
- Тестовая запись удалена (`deleted 1 row(s)`).
- Замечание: в WSL нужен Linux-`node` (`sudo apt install nodejs npm`); npm из Windows через WSL ставит пакеты, но `node` не находится.

## Эталонные маршруты на настоящей Valhalla (14.11.2026, машина владельца)
`node scripts/e2e_routes.js`: 10 PASS, 0 FAIL, 1 SKIP (S10 — только в имитации). Объезды (S02, S04, S05, S06a) — по 1 перестроению.

WSL: если `npm run` запускает Windows-npm (`UNC paths are not supported`), добавьте в `/etc/wsl.conf` секцию `[interop]` с `appendWindowsPath=false` и выполните `wsl --shutdown` в PowerShell.
