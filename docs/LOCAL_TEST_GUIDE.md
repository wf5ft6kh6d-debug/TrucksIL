# Пошаговая локальная проверка TrucksIL (для владельца)

Всё выполняется на вашем компьютере (WSL Ubuntu, папка `~/TrucksIL`). Никакого публичного адреса, платных служб и водителей. Записывайте результат каждого шага: PASS, FAIL или NOT_RUN, а при FAIL сохраняйте вывод команды.

## Шаг 0. Обновить проект и тесты
```bash
cd ~/TrucksIL
git checkout main && git pull
npm ci
npm test
npm run test:py
```
Ожидается: `npm test` без ошибок (237 тестов или больше), `test:py` OK.

## Шаг 1. Запустить стенд с маршрутизацией
```bash
docker compose --profile routing up -d --build
docker compose ps
curl -s localhost:8080/health
```
Ожидается: в `/health` значение `"valhalla":"ok"`. Первая сборка тайлов Valhalla занимает 10–30 минут, файл `data/osm/israel-and-palestine-latest.osm.pbf` должен лежать на месте.

Если база создана давно, примените недостающие миграции (безопасно, они идемпотентные):
```bash
for f in 002_driver_reports 003_adr_tunnels 004_route_structures 005_truck_poi; do
  docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/migrations/$f.sql
done
docker compose restart api
```
Новых миграций после последних изменений нет.

## Шаг 2. Автоматические проверки на настоящем стенде
```bash
npm run test:e2e
(cd web && npm ci && npm run build) && npm run test:web-smoke
```
Ожидается: в e2e нет FAIL (SKIP для S10 и S12e допустим); smoke проходит.

## Шаг 3. Просроченное ограничение и маршрут в обход (ADR-0020)
Подготовка:
```bash
export DATABASE_URL="postgres://trucksil:$(grep ^POSTGRES_PASSWORD= .env | cut -d= -f2)@localhost:5432/trucksil"
REQ='{"from":[34.7818,32.0853],"to":[35.2137,31.7683],"vehicle":{"profileName":"Демо (вымышленный)","heightM":4.0,"widthM":2.55,"lengthM":16.5,"grossWeightT":40,"axleLoadT":11.5}}'
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" > /tmp/route.json
P=$(node scripts/dev_add_test_restriction.js pick < /tmp/route.json); echo "$P"
node scripts/dev_add_test_restriction.js add ${P/,/ } 3.5
docker compose exec db psql -U trucksil -d trucksil -c "UPDATE restrictions SET status='expired' WHERE id='dev-test-max-height';"
```
Проверка:
```bash
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" \
  | jq '{expiredCheck: .trucksil.expiredCheck, warnings: [.trucksil.expiredWarnings[].id], alt: .trucksil.alternativeStatus, avoided: [.trucksil.avoided[].id]}'
```
Ожидается: `expiredCheck: "ok"`, в `warnings` есть `dev-test-max-height`, `avoided` пуст (основной маршрут не меняется), `alt` равен `found` или `none`.

В приложении (`http://localhost:8081`): постройте тот же маршрут с высотой 4,0 м. Должен появиться блок предупреждения. Если `alt: found`, кнопка «Выбрать маршрут в обход» меняет маршрут только после нажатия, а «Вернуться к исходному» возвращает прежний.

Уборка: `node scripts/dev_add_test_restriction.js delete`

## Шаг 4. Просроченная проверка (ADR-0021)
```bash
node scripts/dev_add_test_restriction.js add ${P/,/ } 3.5
docker compose exec db psql -U trucksil -d trucksil -c "UPDATE restrictions SET status='verified', verified_by='test', verified_at=now(), review_due_at=now()-interval '1 day' WHERE id='dev-test-max-height';"
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' -d "$REQ" | jq '.trucksil.avoided[] | {id, status}'
```
Ожидается: запись в `avoided` со статусом `unverified` (хотя в базе она ещё `verified`).

Пробный запуск и запись:
```bash
node scripts/demote_overdue_reviews.js            # только список
node scripts/demote_overdue_reviews.js --apply    # запись
docker compose exec db psql -U trucksil -d trucksil -c "SELECT status FROM restrictions WHERE id='dev-test-max-height'; SELECT event_type, actor FROM restriction_events WHERE restriction_id='dev-test-max-height' ORDER BY id DESC LIMIT 2;"
node scripts/dev_add_test_restriction.js delete
```
Ожидается: пробный запуск показывает запись, `--apply` её понижает; статус в базе `unverified`, последнее событие с актором `system:review-due`.

## Шаг 5. Данные OSM для грузовиков (PR #17)
```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT kind, count(*) FROM truck_poi GROUP BY 1 ORDER BY 1"'
curl -s -X POST localhost:8080/v1/route -H 'content-type: application/json' \
  -d '{"from":[34.78,32.08],"to":[35.21,31.77],"vehicle":{"profileName":"t","heightM":3.8,"widthM":2.5,"lengthM":10,"grossWeightT":18}}' \
  | jq '{speed: (.trucksil.speedLimits|length), lanes: .trucksil.lanes, poi: (.trucksil.poiNearRoute|length)}'
```
Если таблица `truck_poi` пуста, сначала импорт (инструкция в `docs/DEV_SETUP.md`, раздел «Грузовые данные OSM»). Запишите числа: стоянок каждого типа, отрезков скорости, POI на маршруте.

## Шаг 6. Таймер смены и сообщения водителей в браузере
- Таймер: начать смену, перерыв, продолжить, перезагрузить страницу (состояние должно сохраниться), завершить, выгрузить CSV.
- Сообщения: кнопка «Сообщить», клик по карте, тип «hazard». Сообщение появляется с пометкой «не проверено». Проверьте «Всё ещё там» и скрытие модератором через `MODERATOR_TOKEN` (см. `docs/DEV_SETUP.md`).

## Шаг 7. Результаты
Пришлите мне таблицу вида:

| Шаг | Результат | Примечание или вывод ошибки |
|---|---|---|
| 0 | PASS | |
| 2 e2e | PASS | 18 PASS, 2 SKIP |

Краткий чек-лист: `docs/OWNER_TEST_CHECKLIST.md`.

Публиковать прототип можно только после того, как все шаги пройдены, и после вашего письменного разрешения (ADR-0022, п. 6).
