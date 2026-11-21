# Локальный стенд разработки (этап 2, шаг 1)

Стенд поднимает три сервиса через Docker Compose:

| Сервис | Образ | Порт (только localhost) | Назначение |
|---|---|---|---|
| `db` | `postgis/postgis:16-3.5` | 5432 | PostgreSQL + PostGIS, таблицы `restrictions` и `restriction_events` |
| `api` | собирается из `api/Dockerfile` (Node 22) | 8080 | HTTP API: `/health`, `/v1/restrictions`, `/v1/route`, `/v1/poi` |
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
3. Конфликты объезжаются **независимо от статуса** (verified/unverified/disputed): объезд — всегда безопасное направление. Исключение строится ступенчато (ADR-0011): сначала узкие прямоугольники (±7 м) вокруг **участка маршрута** в пределах ±30 м от ближайшей к ограничению точки — исключается только реально использованное ребро; если следующий маршрут снова проходит через то же ограничение, добавляется многоугольник радиусом 20 м вокруг самого ограничения (`ST_Buffer` по geography); если и это не помогло — `409`. Всё передаётся в Valhalla как `exclude_polygons`; до `MAX_REROUTES` (8) перестроений, с предисключением конфликтов в 3 км от первого маршрута, сопоставлением OSM-записей по way id маршрута и бюджетом периметра Valhalla (ADR-0016; переменные `MAX_REROUTES`, `PRE_EXCLUDE`, `MAX_PRE_EXCLUSIONS`, `VALHALLA_MAX_EXCLUDE_PERIMETER_M`, `ROUTE_WAY_MATCH`). Диагностика: `POST /v1/route?debug=1` или `node scripts/explain_route.js 34.7818,32.0853 35.2137,31.7683 4.0 40` — какие ограничения избегаются и почему, со ссылками OSM. Без геометрии ограничения сразу используется 20 м.
4. Если конфликт остаётся — `409` со списком `conflicts`; если Valhalla не находит маршрут в обход — `422`. Небезопасный маршрут как успешный не возвращается.
5. `onRoute` — ограничения на итоговом маршруте, которые ТС не нарушает (со статусом). Маршрут никогда не объявляется безопасным из-за непроверенных данных, а отсутствие записей ничего не гарантирует: `unverifiedCoverage` остаётся `"unknown"`.

`valueSource` и `value` показываются ровно как в базе (значение со знака — ADR-0004).

Направление (`direction`, ADR-0011): для ограничения-линии (`LineString`) с `forward`/`backward` сравниваются азимут маршрута (±15 м вокруг ближайшей точки) и азимут участка линии в этой точке; расхождение ≤ 60° — проезд «по оцифровке» (`forward`), ≥ 120° — «против» (`backward`). Ограничение для другого направления игнорируется (нет ни в `avoided`, ни в `onRoute`). Точки, `both` и случаи, когда направление определить нельзя (вырожденная линия, маршрут короче 5 м у точки), — ограничение применяется (консервативно).

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
E2E_STRICT=1 npm run test:e2e                     # абсолютные ожидания (без учёта базового маршрута)
```

Для каждого сценария скрипт `scripts/e2e_routes.js`: строит базовый маршрут через API → вычисляет точки `{"onRouteFraction": f}` по его линии → записывает вымышленные ограничения → вызывает `POST /v1/route` → сверяет ожидания → **всегда** удаляет свои записи (в т. ч. после ошибки; перед запуском удаляются и остатки прерванного прогона). В конце печатается таблица PASS/FAIL/SKIP; при любом FAIL (или если в базе остались строки `e2e-*`) код выхода ненулевой. Сравниваются только засеянные `e2e-*` записи, а число перестроений — относительно базового маршрута (ADR-0016): для объездов `reroutes ≥ max(minReroutes, базовые)`, для сценариев без объезда — только статус 200 и отсутствие засеянного id в `avoided`. Если базовый маршрут уже не строится из-за реальных данных — SKIP с причиной «baseline blocked by non-test data». `E2E_STRICT=1` — прежняя абсолютная проверка.

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
| S11a | Тель-Авив → Иерусалим | линия 40 м, 3,8 м, `forward`, оцифрована по ходу движения → в `avoided` |
| S11b | Тель-Авив → Иерусалим | то же, оцифрована против хода → другая проезжая часть, игнорируется, без перестроения |
| S11c | Тель-Авив → Иерусалим | `backward`, оцифрована против хода → в `avoided` |
| S11d | Тель-Авив → Иерусалим | `both`, оцифрована против хода → в `avoided` |

На настоящей Valhalla число перестроений может быть больше 1 (рядом с исключённой точкой может оказаться параллельная проезжая часть), поэтому для объездов задан диапазон `minReroutes`…`maxReroutes` (1…3). Если точка `onRouteFraction` попала на участок без объезда, сценарий с объездом получит 422 — выберите другую долю.

### Как добавить сценарий

Добавьте объект в `scenarios` файла `test/scenarios/routes.json`:

```json
{
  "id": "S12", "description": "что проверяем",
  "from": "haifa", "to": "telAviv", "vehicle": "semi45",
  "restrictions": [{ "id": "s12-width", "type": "max_width", "value": 2.4, "unit": "m",
                     "status": "unverified", "valueSource": "posted_sign", "where": { "onRouteFraction": 0.3 } }],
  "expected": { "status": 200, "avoidedIds": ["s12-width"], "onRouteIds": [], "minReroutes": 1, "maxReroutes": 3 }
}
```

- `from`/`to` — имя из `places` или `[lon, lat]`; `vehicle` — имя из `vehicles` или полный профиль.
- `where` — `[lon, lat]` или `{"onRouteFraction": 0…1}` (доля длины базового маршрута) — точка; `{"onRouteFraction": f, "lineM": 40, "reversed": false}` — линия длиной ~`lineM` м по маршруту, оцифрованная по ходу движения (`reversed: true` — против). Поле ограничения `direction` — `both` (по умолчанию) / `forward` / `backward`. id указывается без `e2e-`, префикс добавляется автоматически.
- `expected`: `status` (200/409/422), `avoidedIds`, `onRouteIds`, `absentIds`, `conflictIds`, `minReroutes`/`maxReroutes`, `minVerifiedOnRoute`. Для сценариев, которые нельзя воспроизвести на настоящей Valhalla, — `"mockOnly": true` и `"mock": {"noDetour": true}`.
- Затем `npm test` (сценарий автоматически станет отдельным тестом) и `npm run test:e2e` на стенде.

## Известные ограничения

- Собственные ограничения TrucksIL применяются только после построения маршрута (проверка по линии + `exclude_polygons`), а не внутри графа Valhalla; базовый маршрут по-прежнему опирается на теги OSM, значения которых — лишь кандидаты (ADR-0006). Где в данных TrucksIL пробелы, узнать нельзя, поэтому `unverifiedCoverage` всегда `"unknown"`.
- `exclude_polygons` исключает все рёбра, пересекающие многоугольник. Первая ступень — узкий (±7 м) прямоугольник вокруг использованного ребра, но он плоский: дорога, пересекающая маршрут **точно в месте ограничения** (под мостом/над ним), всё равно попадает в него — в Valhalla нет уровней (z) для исключений. Если узкое исключение не помогло, применяется прежний многоугольник 20 м (может задеть соседнюю проезжую часть или съезды развязки) → маршрут длиннее или `422`.
- Обнаружение «на маршруте» по-прежнему в радиусе 50 м: точечное ограничение без направления на одной проезжей части продолжает влиять на соседнюю (параллельную) в пределах 50 м. Чтобы этого избежать, вносите ограничение линией по нужной проезжей части с `direction`.
- `direction` учитывается только для линий; точка не задаёт направление и применяется в обе стороны. Временные окна проверяются на момент запроса, а не на время прохождения участка.
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

## Веб-клиент (PWA-прототип, этап 4) / Web client

> **Прототип. Не для навигации.** Баннер с этим текстом и с оговоркой «Отсутствие ограничений ≠ безопасно» показан постоянно.

Код — `web/` (vanilla JS ES modules + Vite `8.3.5`, MapLibre GL JS `6.15.0`, ajv `8.20.0`; версии зафиксированы точно в `web/package.json` / `web/package-lock.json`, без CDN).

**Через Docker Compose** (сервис `web`: nginx раздаёт собранный клиент и проксирует `/api/*` → `api:8080`):

```bash
docker compose up -d --build          # db + api + web
# открыть http://localhost:8081  (порт: WEB_PORT в .env, по умолчанию 8081)
```

Почему прокси, а не CORS: браузер работает с одним origin (`/api/v1/route`), API остаётся без CORS-заголовков и не становится доступным другим сайтам из браузера. Тот же путь `/api` в режиме разработки даёт прокси Vite.

**Режим разработки** (API уже запущен на `localhost:8080`):

```bash
cd web && npm ci && npm run dev       # http://127.0.0.1:5173, /api -> http://127.0.0.1:8080 (TRUCKSIL_API переопределяет)
npm run build                         # -> web/dist
```

Что есть: профиль машины (US-01) с проверкой по **тому же** `data/vehicle-profile.schema.json` и тем же ajv, что в API; профили в `localStorage`; точки маршрута кликом по карте или вводом `долгота,широта`; линия маршрута (polyline6 декодируется общим модулем `api/src/polyline.mjs` — API подключает его через `require`, Node ≥ 22.12); панель ограничений: «Объезжено», «На маршруте», счётчики покрытия, значение показывается как пришло из API с единицей, метка источника («по знаку») и статус (непроверено/проверено); маркеры ограничений на карте (API теперь отдаёт `geometry` GeoJSON в элементах `avoided`/`onRoute`/`conflicts`). Ошибки 400/409/422/502/503 и недоступность сети показываются явно; при 409/422 выводятся конфликты, маршрут **никогда** не рисуется (рисуется только при 200).

Оговорка «как хранится»: API приводит `value_numeric` к числу (`Number`), поэтому хвостовые нули (`4.20`) не сохраняются; округления и пересчёта единиц нет.

**Языки:** he (RTL, по умолчанию), ar (RTL), ru, en; атрибуты `lang`/`dir` у `<html>` переключаются. Тексты he/ar/en — машинного качества и **требуют проверки носителями** до любого показа пользователям.

**PWA:** `manifest.webmanifest`, иконки, `sw.js` кэширует только оболочку приложения (HTML, хэшированные `/assets/*`, иконки). Ответы `/api/*` и тайлы карты **не кэшируются** (устаревшие данные об ограничениях опасны). Service worker регистрируется только в production-сборке.

**Тайлы OSM:** прототип использует публичные растровые тайлы `tile.openstreetmap.org`. Это допустимо для локальной разработки с небольшим трафиком, но **не для production** — см. [OSM Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) (нужен свой тайловый сервер или коммерческий провайдер; атрибуция «© OpenStreetMap contributors» обязательна и показана на карте).

**Тесты:** юнит-тесты `web/test/*.test.js` (i18n, валидация, хранилище, view-model ответов включая ошибки) входят в `npm test` в корне. Smoke-тест в браузере (Playwright + установленный Chromium, API замокан, тайлы подменены — сеть не нужна):

```bash
(cd web && npm run build) && npm run test:web-smoke -- /tmp/pwa.png   # аргумент — необязательный путь скриншота
```

## Веб-клиент на машине владельца (15.11.2026)
- `http://localhost:8081`, маршрут Тель-Авив → Иерусалим на настоящей Valhalla: 67,5 км / 77 мин без ограничений.
- С вымышленным мостом 3,5 м (`dev_add_test_restriction.js`) и тягачом 4,0 м: 69,0 км / 87 мин, перестроений 1; мост в «объезжено» (по знаку, не проверено, причина `heightM 4 > limit 3.5 m`), красный маркер на месте моста, маршрут обходит его.
- Проверены интерфейсы на иврите и арабском (RTL), выбор точки кликом на карте.
- Переводы he/ar машинные — нужна вычитка носителем языка.

## Сообщения водителей (этап 5, первая часть) / Driver reports
Непроверенные сообщения водителей (пробка, авария, опасность, камера, низкий габарит, другое). Хранятся отдельно от `restrictions` и **не участвуют** в проверке маршрута — подробности в ADR-0012.

**Миграция.** `db/initdb.sh` применяет все `db/migrations/*.sql` по порядку, но только при **первой** инициализации тома БД. На новом томе `002_driver_reports.sql` применится сам. На существующем томе примените вручную (миграция идемпотентна):
```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/002_driver_reports.sql
```
(Альтернатива — пересоздать том: `docker compose down -v`, при этом удалятся все данные БД.)

**Переменные `.env`:**
- `REPORTS_SALT` — соль для хеширования анонимного id клиента (`openssl rand -hex 32`). Пусто → dev-соль и предупреждение в логе API.
- `MODERATOR_TOKEN` — токен модератора. Пусто → модерация отключена (всегда 403).

**API** (анонимный id клиента — заголовок `x-trucksil-client`, 16–128 символов `[A-Za-z0-9_-]`; веб-клиент генерирует его сам и хранит в `localStorage`):
```bash
CID=devclient0000000001
curl -s -X POST localhost:8080/v1/reports -H 'content-type: application/json' -H "x-trucksil-client: $CID" \
  -d '{"type":"hazard","position":[34.78,32.08],"note":"масло на дороге"}'
curl -s 'localhost:8080/v1/reports?bbox=34.7,32.0,34.9,32.2'
curl -s -X POST localhost:8080/v1/reports/<id>/vote -H 'content-type: application/json' -H "x-trucksil-client: $CID" -d '{"vote":"confirm"}'
curl -s -X POST localhost:8080/v1/reports/<id>/moderate -H 'content-type: application/json' -H "x-moderator-token: $MODERATOR_TOKEN" -d '{"action":"hide"}'
```
Правила: координаты только внутри Израиля, комментарий ≤ 280 символов; время жизни traffic 1 ч / accident 3 ч / hazard 12 ч / camera и low_clearance 30 сут / other 6 ч; не более 5 сообщений за 10 мин на клиента (429); один голос на сообщение (повтор — 409); автоскрытие при ≥ 3 отклонениях и отклонений больше, чем подтверждений. Ответ `/v1/route` содержит `trucksil.reports` — сообщения в 100 м от маршрута (`null`, если поиск не удался; маршрут при этом не блокируется).

**Веб-клиент:** кнопка «Сообщить» → клик по карте (или долгое нажатие / правый клик) → тип и комментарий. Сообщения показываются отдельным фиолетовым слоем и списком с пометкой «сообщение водителя, не проверено», с кнопками «Всё ещё там» / «Уже нет».

**Ограничения прототипа:** лимит частоты хранится в памяти процесса (сбрасывается при перезапуске, не общий для нескольких экземпляров); новые сообщения сразу видимы (без премодерации); интерфейса модератора нет — только эндпоинт.

## Покрытие маршрута: мосты/тоннели без данных (ADR-0014) / Route coverage
После построения маршрута API вызывает у Valhalla `POST /trace_attributes` (`edge_walk`) и отдаёт в `trucksil.coverage`: `status` (`computed`/`unknown`), `structuresOnRoute`, `structuresWithData`, `noDataSegments`. Сооружение «с данными», если ограничение TrucksIL лежит в пределах 30 м. Ошибка `trace_attributes` → `status: "unknown"` (маршрут всё равно возвращается). Проезды ПОД мостами не учитываются (ограничение подхода).

Проверка на настоящей Valhalla (нужно владельцу):
```sh
curl -s localhost:8002/trace_attributes -H 'content-type: application/json' -d '{"encoded_polyline":"<shape из /route>","shape_match":"edge_walk","costing":"truck","filters":{"attributes":["edge.bridge","edge.tunnel","edge.way_id","edge.begin_shape_index","edge.end_shape_index","shape"],"action":"include"}}' | jq '.edges[] | select(.bridge or .tunnel)'
```
Ожидается: `edges[]` с `bridge`/`tunnel` (bool), `way_id`, индексами формы и строка `shape`. Тесты: `test/api/coverage.test.js`, `web/test/viewModel.test.js`.

## Грузовой профиль и тоннели ADR (ADR-0013)

- Профиль ТС (`data/vehicle-profile.schema.json`) получил необязательные `axleCount` (→ Valhalla `axle_count`) и `hazmat.adrTunnelCode` (код тоннеля из документа ADR: `B`, `B1000C`, `C/D`, `D/E`, `E`, `-` …). Старые профили остаются валидными.
- В каждый запрос к Valhalla добавляется `hgv_no_access_penalty: 43200` — дороги без доступа грузовиков фактически запрещены.
- Ограничение `restrictionType: "adr_tunnel"` (`unit: "adr_tunnel_category"`, `value` `B`..`E`) хранится в колонке `value_text`. Применить миграцию на существующей БД:

  ```bash
  docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/003_adr_tunnels.sql
  ```

  (миграцию можно запускать повторно; на новой БД она применяется автоматически, если `db/migrations` смонтирован в `docker-entrypoint-initdb.d`.)
- Шаблон записи тоннеля: `data/examples/tunnels/` (только вымышленные данные).
- Эталонные сценарии S12a–S12e (`test/scenarios/routes.json`) проверяют тоннели; S12e — только с mock.

## Проверка на машине владельца (21.11.2026): профиль грузовика, тоннели ADR, покрытие
- Миграции 002 и 003 применены к существующей базе.
- `npm run test:e2e`: 18 PASS, 0 FAIL, 2 SKIP (S10, S12e — только в имитации). S02 и S11a — по 1 перестроению (узкое исключение сработало без эскалации до 20 м); S11b — 0 перестроений (ограничение другого направления); S12a–d прошли.
- Покрытие Тель-Авив → Иерусалим: `status: computed`, 21 сооружение (мосты и тоннели), с данными TrucksIL — 0; `trace_attributes` Valhalla 3.9.2 вернул ожидаемый формат.
- Замечание: соседние тоннели/мосты из разных OSM way считаются отдельными сооружениями (например, тоннели у въезда в Иерусалим дали 4 записи). Можно объединять смежные участки одного типа.

## Проезды под мостами в покрытии маршрута (ADR-0014, миграция 004)
Объединение смежных мостов/тоннелей работает сразу. Чтобы считались проезды ПОД мостами, нужно один раз загрузить их из OSM-выгрузки в локальную БД (данные ODbL — только локально, не коммитить):

```bash
# 1. миграция (идемпотентна; на новой БД применяется автоматически)
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/004_route_structures.sql
# 2. загрузка (venv с osmium, как для osm_bridge_clearance.py; Python-драйвер БД не нужен)
source .venv/bin/activate && pip install osmium
python3 scripts/load_osm_underpasses.py data/osm/israel-and-palestine-latest.osm.pbf --sql \
  | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
#    (или, если psql установлен на хосте: python3 scripts/load_osm_underpasses.py <pbf> "$DATABASE_URL")
# 3. проверка
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" | jq .trucksil.coverage  # REQ — запрос Тель-Авив→Иерусалим (см. выше)
```
Повторный запуск загрузки заменяет таблицу целиком (TRUNCATE + COPY в одной транзакции). Ожидается `underpassStatus: "computed"`, `underpassesOnRoute`, `underpassesWithData`, `noDataUnderpasses[]` (`osmMaxheightCandidate` — только подсказка из OSM). Пустая/отсутствующая таблица → `underpassStatus: "not_loaded"`. Путь к .pbf подставьте свой. Тесты: `test/api/coverage.test.js`, `python3 -m unittest scripts/test_load_osm_underpasses.py`.

## Офлайн-карта (ADR-0015) / Offline map

Файл карты собирается один раз на машине владельца (WSL2, Docker) из того же `.osm.pbf`, что и Valhalla:

```bash
mkdir -p data/tiles
docker run --rm -e JAVA_TOOL_OPTIONS="-Xmx3g" \
  -v "$PWD/data:/data" ghcr.io/onthegomap/planetiler:0.10.2 \
  --osm-path=/data/osm/israel-and-palestine-latest.osm.pbf \
  --output=/data/tiles/israel.pmtiles \
  --download --only-layers= --languages=he,ar,ru,en --force
```

- `--download` скачивает только вспомогательные наборы (Natural Earth, water polygons, ~1 ГБ, один раз в `data/sources/` — добавьте `data/sources/` в .gitignore или удалите после сборки).
- Ожидаемо: 5–15 минут, 2–4 ГБ RAM, результат ~80–150 МБ (z0–14). Цифры оценочные — запишите фактические.
- Глифы (шрифты подписей), без CDN: из репозитория `protomaps/basemaps-assets` скопируйте папку `fonts/Noto Sans Regular` в `data/tiles/fonts/` (должны появиться файлы `data/tiles/fonts/Noto Sans Regular/0-255.pbf` и т.д.); запишите хеш коммита в `data/tiles/SOURCES.txt`. Проверьте подписи на иврите и арабском — если какой-то диапазон отсутствует, подписи этого письма не отобразятся.
- `docker compose up -d --build web` — nginx монтирует `./data/tiles` в `/srv/tiles` и отдаёт `/tiles/israel.pmtiles` с Range. Проверка: `curl -sI -H 'Range: bytes=0-7' http://localhost:8081/tiles/israel.pmtiles` → `206`. В dev (`npm run dev`) то же отдаёт плагин в `web/vite.config.js`.
- Без файла клиент показывает онлайн-тайлы OSM и предупреждение «Файл офлайн-карты не установлен» (только для разработки).
- Кеш SW: просмотренные районы + тайлы вдоль маршрута, до 200 МБ (LRU); пересборка файла (новый ETag) сбрасывает кеш.

## Голос, навигация, симуляция (ADR-0015) / Voice & navigation

- Раздел «Навигация (тестовый режим)»: «Старт по GPS» (браузер спросит разрешение; нужен HTTPS или localhost), «Симуляция поездки» (скорость и смещение от маршрута — для проверки за столом), «Голосовые подсказки».
- Язык инструкций Valhalla = язык UI на момент запроса (he-IL / ru-RU / ar-SA / en-US). Наличие голоса зависит от устройства: в Windows/Android голос иврита/арабского может отсутствовать — тогда подсказки беззвучны и показано сообщение.
- Проверка схода за столом: смещение 200 м, скорость 60 → через ~10 с «Сход с маршрута», затем автоматическое перестроение (не чаще раза в 30 с) от текущей (симулированной) точки.
- Офлайн: без сети последний маршрут показывается с плашкой «Офлайн: маршрут от <время>, ограничения могут быть устаревшими»; перестроение офлайн невозможно.
- Приватность: позиция не сохраняется; отправляется только как точка старта запроса маршрута.
- Тесты: `npm test` (web/test/nav.test.js, swPolicy.test.js, style.test.js), `cd web && npm run build && cd .. && npm run test:web-smoke`.

## Проверка на машине владельца (21.11.2026): проезды под мостами и PMTiles
- Миграция 004 применена; `load_osm_underpasses.py` загрузил 3 493 проезда (совпадает с замером `osm_bridge_clearance.py`).
- planetiler 0.10.2: `israel.pmtiles` 96 МБ за 4 мин 18 с (из них 1,5 мин — скачивание вспомогательных данных ~1,4 ГБ в `data/sources/`).
- Покрытие Тель-Авив → Иерусалим: мостов/тоннелей 17 (было 21 до объединения соседних участков), проездов под мостами на маршруте 35, с данными TrucksIL — 0; `underpassStatus: computed`.
- Тайлы OpenMapTiles требуют видимой атрибуции «© OpenMapTiles © OpenStreetMap contributors».

## Высотные ограничения из OSM как кандидаты (ADR-0006, дополнение)
Загружает `maxheight` из OSM в `restrictions` со статусом `unverified` (маршрут их избегает, покрытие считает «с данными», но не «проверено»). Данные ODbL — только локально, не коммитить. Нужны venv с osmium (как выше) и `node` (проверка схемы через Ajv).

```bash
source .venv/bin/activate
# 1. импорт (идемпотентен: удаляет только id LIKE 'osm-maxheight-%' и вставляет заново, одна транзакция)
python3 scripts/import_osm_maxheight.py data/osm/israel-and-palestine-latest.osm.pbf --sql \
  | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
#    статистика (crossing / way / node / skipped_*) и итог проверки схемы — в stderr
# 2. проверка количества
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT GeometryType(geometry), value_source, count(*) FROM restrictions WHERE id LIKE '"'"'osm-maxheight-%'"'"' GROUP BY 1,2 ORDER BY 1,2"'
# 3. эталонные сценарии и покрытие
npm run test:e2e
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" \
  | jq '.trucksil.coverage | {structuresOnRoute, structuresWithData, structuresWithVerifiedData, underpassesOnRoute, underpassesWithData, underpassesWithVerifiedData}'
```
Ожидаемо (по `docs/OSM_COVERAGE.md`): порядка 684 ways + 98 узлов с высотой, из них до 575 проездов под мостами; после фильтров (мосты, нечисловые, выбросы, а с ADR-0017 — ещё и `skipped_service_parking`: `service=parking_aisle|driveway|drive-through`, их проезды под мостами и узлы только на таких way) записей будет меньше, чем 1034 из прошлого импорта (ниже) — запишите фактические числа, в том числе `skipped_service_parking`. `structuresWithVerifiedData` / `underpassesWithVerifiedData` останутся 0, пока нет проверенных записей. Если e2e-сценарии изменятся из-за новых объездов (OSM-кандидаты на пути), это ожидаемо — зафиксируйте, какие. Откат: `DELETE FROM restrictions WHERE id LIKE 'osm-maxheight-%';`. Тесты: `python3 -m unittest scripts/test_import_osm_maxheight.py`, `test/api/coverage.test.js`, `web/test/viewModel.test.js`.

## Проверка на машине владельца (21.11.2026): кандидаты OSM + сопоставление по way_id
- Импорт: 1034 записи (crossing 559, way 382, node 93), пропущено 60; все прошли схему.
- До сопоставления по way_id: Тель-Авив → Иерусалим объезжал 8 соседних дорог (тоннель под улицей, подземная парковка и т.п.), e2e 7/11 FAIL, S04 422, S12b/c 409.
- После (ADR-0016): e2e (относительный режим) 18 PASS, 0 FAIL, 2 SKIP; у всех базовых маршрутов reroutes 0. Сценарии с объездом — 1–2 перестроения.

## Таймер смены (US-06, ADR-0018) / Shift timer
Панель «Таймер смены» в PWA: начать / перерыв / продолжить / завершить, суммы вождения, перерывов и смены, следующее напоминание. **Это напоминание, не юридическое подтверждение соблюдения режима труда и отдыха.**
- Лимиты настраиваются (по умолчанию смена 12 ч, вождение 9 ч, напоминание о перерыве после 4,5 ч непрерывного вождения; пустое поле — выкл.). Напоминания за 2 ч, 1 ч, 30 мин и в момент лимита, каждое один раз за смену.
- Каналы: сообщение на экране; голос — если включён «Голос» в навигации; системное уведомление — после нажатия «Включить уведомления».
- Данные только в `localStorage` (`trucksil.shift.v1`, `trucksil.shift.settings.v1`, `trucksil.shift.history.v1`); история — последние 7 смен, экспорт CSV в браузере, кнопка «Очистить историю».
- Логика: `web/src/shift/timer.js` (тесты `web/test/shift.test.js`), UI: `web/src/shift/ui.js`. Smoke (`npm run test:web-smoke`) проверяет start → напоминание → перерыв → продолжение → перезагрузку → завершение → CSV с поддельными часами Playwright.
- Переводы he/ar — машинные, нужна проверка носителем.

## Грузовые данные OSM: скорости, полосы, стоянки (ADR-0017) / OSM truck data
Только для показа, всегда «OSM, не проверено» (ODbL, только локальная БД, не коммитить). На маршрут не влияют. Отображение в веб-клиенте — отдельный шаг.
```bash
# 1. миграция 005 (идемпотентна; на новом томе применяется автоматически)
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/005_truck_poi.sql
# 2. импорт стоянок/площадок отдыха/АЗС для грузовиков (venv с osmium, как выше; повторяемо: DELETE + вставка в одной транзакции)
python3 scripts/import_osm_truck_poi.py data/osm/israel-and-palestine-latest.osm.pbf --sql \
  | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
#    статистика (parking / rest_area / fuel_hgv / skipped_no_geometry) — в stderr
# 3. повторный импорт высот с фильтром парковок (см. раздел выше), затем пересчёт e2e
# 4. проверка
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT kind, count(*) FROM truck_poi GROUP BY 1 ORDER BY 1"'
curl -s 'http://localhost:8080/v1/poi?bbox=34.7,31.7,35.3,32.2&kind=parking,rest_area' | head -c 600; echo
docker compose restart api   # новые поля маршрута
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' \
  -d '{"from":[34.78,32.08],"to":[35.21,31.77],"vehicle":{"profileName":"t","heightM":3.8,"widthM":2.5,"lengthM":10,"grossWeightT":18}}' \
  | jq '{speed: (.trucksil.speedLimits|length), first: .trucksil.speedLimits[0:3], lanes: .trucksil.lanes, poi: (.trucksil.poiNearRoute|length)}'
```
Поля ответа `/v1/route`: `trucksil.speedLimits` (`[{fromIndex,toIndex,kmh,truckKmh?,source:'osm',status:'unverified'}]`, индексы — точки формы; пробелы = неизвестно; `null` — trace не удался), `trucksil.lanes` (сводка; сами массивы — `trip.legs[].maneuvers[].lanes`, запрос с `turn_lanes: true`), `trucksil.poiNearRoute` (до 50 в 500 м; `null` — таблица пуста/нет). Запишите: число отрезков скорости и есть ли `truckKmh` (т. е. `maxspeed:hgv`), число манёвров с полосами, число POI на маршруте. `maxspeed:hgv` Valhalla уже учитывает во времени пути (`truckcost.cc`). Откат: `DELETE FROM truck_poi;` (или `DROP TABLE truck_poi;` — API вернёт `poiNearRoute: null`). Тесты: `test/api/osmExtras.test.js`, `python3 -m unittest scripts/test_import_osm_truck_poi.py scripts/test_import_osm_maxheight.py`.
