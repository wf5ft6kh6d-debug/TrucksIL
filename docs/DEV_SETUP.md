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
# {"status":"ok","db":"ok","valhalla":"disabled"}
curl -s 'localhost:8080/v1/restrictions?bbox=34.2,29.4,35.9,33.4'
# {"type":"FeatureCollection","features":[]}
```

`POST /v1/route` в этом режиме отвечает `503` с понятным сообщением «routing disabled».

Миграции из `db/migrations/*.sql` применяются автоматически **только при первом запуске** (когда том `db-data` пуст). Чтобы пересоздать базу с нуля: `docker compose down -v` (удалит все данные БД).

## 4. Запуск с маршрутизацией (Valhalla)

1. Скачайте выгрузку OSM вручную (≈ 100–150 МБ) с Geofabrik: страница <https://download.geofabrik.de/asia/israel-and-palestine.html>, файл `israel-and-palestine-latest.osm.pbf`. Данные OSM — под лицензией ODbL, укажите атрибуцию «© OpenStreetMap contributors».
2. Положите файл в `data/osm/`:
   ```bash
   mv ~/Downloads/israel-and-palestine-latest.osm.pbf data/osm/
   ```
   Папка `data/osm/` в git игнорируется (кроме `.gitkeep`). Сам стенд ничего не скачивает.
3. В `.env` раскомментируйте/задайте `VALHALLA_URL=http://valhalla:8002`.
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

Ответ — ответ Valhalla `/route` (поле `trip`) плюс блок:

```json
"trucksil": {"disclaimer": "prototype, not for navigation", "unverifiedCoverage": "unknown"}
```

Сопоставление полей профиля с `costing_options.truck` Valhalla: `heightM→height`, `widthM→width`, `lengthM→length` (метры), `grossWeightT→weight`, `axleLoadT→axle_load` (тонны), наличие `hazmat→hazmat: true`.

Коды ответов: `400` — неверный JSON/координаты/профиль (с перечнем ошибок), `503` — Valhalla отключена или недоступна, `502` — Valhalla вернула ошибку 5xx; ошибки 4xx Valhalla (например, «маршрут не найден») передаются как есть.

## 5. Тесты

```bash
npm ci
npm test
```

Тесты API (`test/api/`) не требуют Docker: база и Valhalla подменяются заглушками.

## Известные ограничения

- Собственные ограничения TrucksIL из таблицы `restrictions` **пока не передаются** в Valhalla: маршрут строится только по тегам OSM (`maxheight`, `maxweight` и т. п.), а их значения — лишь кандидаты (ADR-0006). Поэтому `unverifiedCoverage` всегда `"unknown"`.
- Нет аутентификации, ограничения частоты запросов и HTTPS — стенд только для локальной машины (порты привязаны к `127.0.0.1`).
- `/v1/restrictions` возвращает не более 5000 объектов и только записи с геометрией.
- `/health` отвечает `503`, если БД или включённая Valhalla недоступна; из-за этого Docker-healthcheck контейнера `api` тоже покажет `unhealthy`.
- Высоты рельефа (`build_elevation`) и пробки не используются.
- Сервис `valhalla` в этом окружении разработки ещё ни разу не запускался на реальном `.pbf`; первый запуск на вашей машине — фактически проверка конфигурации.
