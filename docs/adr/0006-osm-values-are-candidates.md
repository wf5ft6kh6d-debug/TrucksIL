# ADR-0006: Значения из OSM — только кандидаты

- **Статус:** Принято
- **Дата:** 2026-11-14

## Контекст
OpenStreetMap содержит теги `maxheight`, `maxweight` и др., но их полнота и точность для Израиля не гарантированы (`docs/OSM_COVERAGE.md`). Данные распространяются по лицензии ODbL с требованиями атрибуции и share-alike.

## Решение
- Ограничения из OSM импортируются со статусом `unverified`; `valueSource = unknown`, кроме случая `source:maxheight=sign` (тогда `posted_sign`, статус всё равно `unverified`).
- Везде, где используются данные OSM, указывается атрибуция «© участники OpenStreetMap, ODbL».
- Сырые выгрузки OSM (`.osm.pbf` и т. п.) не хранятся в репозитории; коммитятся только скрипты и агрегаты.

## Последствия
- OSM даёт предупреждения и кандидатов на проверку, но не «зелёный» маршрут.
- Нужен процесс перевода кандидатов в `verified` по `docs/DATA_VERIFICATION.md`.
- Производные базы данных из OSM подпадают под share-alike (см. ADR-0010).

## Дополнение (21.11.2026): импорт OSM maxheight в `restrictions`
- `scripts/import_osm_maxheight.py` загружает высотные ограничения из OSM-выгрузки в таблицу `restrictions` как кандидатов: `status = unverified`, `restrictionType = max_height`, `unit = m`, `source = {name: "OpenStreetMap contributors", reference: "osm:<type>/<id>@<дата выгрузки>", url, license: "ODbL-1.0"}`, `observedAt` — максимальная метка времени объектов выгрузки. `id` стабильные: `osm-maxheight-way<id>`, `osm-maxheight-way<дорога>-crossing<мост>`, `osm-maxheight-node<id>`.
- Источники: (a) проезд под мостом, если высота задана на way дороги снизу — точка пересечения (тогда LineString этого way не создаётся, чтобы не исключать весь way); (b) прочие highway-ways с высотой, кроме мостов (тоннели, covered, обычные дороги) — LineString, направление по `oneway`; (c) узлы с высотой на highway-ways — точка. Узлы рядом с проездом не дублируются как (a).
- `valueSource`: `posted_sign` при `source:maxheight=sign` или `maxheight:signed=yes`; `measured`, если использован `maxheight:physical`; иначе `unknown`. Хранится одно значение, `maxheight` предпочтительнее `maxheight:physical`. Схема не менялась (все значения уже были в enum).
- Нечисловые значения (`default`, `none`, `below_default`, …) и выбросы (< 2 м, > 7 м) пропускаются и считаются в статистике.
- Маршрутизация избегает этих кандидатов так же, как любых ограничений (ADR-0002: избегать — всегда безопасное направление), и показывает их статус `unverified`. Это может давать лишние объезды из-за ошибок OSM — приемлемо до проверки.
- Покрытие (ADR-0014) считает их «с данными», но новые поля `structuresWithVerifiedData` / `underpassesWithVerifiedData` показывают, сколько из них имеют проверенные (`verified`) данные; веб-панель: «с данными: M (проверено: K)».
- Повторный импорт в одной транзакции удаляет только строки `id LIKE 'osm-maxheight-%'`; ручные, MoT и dev-записи не затрагиваются. Аудит-триггер пишет по событию на каждую удалённую и вставленную строку.
- Каждая запись перед загрузкой проверяется по `data/restrictions.schema.json` (Ajv через `node scripts/validate_restrictions.js`, тот же валидатор, что в `npm test`; Python-пакет jsonschema не нужен).
