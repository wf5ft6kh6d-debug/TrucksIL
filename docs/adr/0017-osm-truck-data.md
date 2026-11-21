# ADR-0017: Грузовые данные OSM на маршруте: скорости, полосы, стоянки (только для показа)

- **Статус:** Принято
- **Дата:** 2026-11-21
- **Дополняет:** ADR-0006 (значения OSM — кандидаты), ADR-0014 (тот же вызов `/trace_attributes`), ADR-0016 (фильтр парковок в импорте)

## Контекст
Навигаторы-конкуренты (`docs/research/NAVIGATORS.md`) показывают грузовые ограничения скорости (`maxspeed:hgv`), подсказки по полосам (`turn:lanes`) и стоянки для грузовиков. Всё это есть в OSM и частично уже читается Valhalla 3.9.2 (образ `ghcr.io/valhalla/valhalla-scripted:3.9.2`). Проверено по исходникам тега `3.9.2` (valhalla/valhalla, коммит `a919bb6`):
- `src/mjolnir/pbfgraphparser.cc`: теги `maxspeed:hgv`, `maxspeed:hgv:forward`, `maxspeed:hgv:backward` → `truck_speed` ребра (`lua/graph.lua` нормализует значения).
- `src/sif/truckcost.cc` (`TruckCost::EdgeCost`): скорость = `min(скорость ребра, truck_speed ? min(truck_speed, top_speed) : top_speed)` — т. е. **`maxspeed:hgv` уже влияет на время и стоимость** грузового маршрута (ETA), без нашей доработки.
- `valhalla/baldr/attributes_controller.h`, `src/tyr/trace_serializer.cc`, `docs/docs/api/map-matching.md`: атрибуты `edge.speed_limit` («Edge speed limit … default kilometers per hour»; значение `"unlimited"` или отсутствие при 0) и `edge.truck_speed` (выводится только если > 0).
- `docs/docs/api/route/api-reference.md`, `src/tyr/route_serializer_valhalla.cc`: опция запроса `turn_lanes: true` → у манёвра может быть массив `lanes` (`directions`, `valid`, `active` — битовые маски из `turn:lanes`).
Стоянок для грузовиков в Valhalla нет — нужен свой небольшой слой.

## Решение
- **Скорости.** В запрос `/trace_attributes` (ADR-0014, запоминается на запрос — финальный маршрут трассируется один раз) добавлены `edge.speed_limit` и `edge.truck_speed`. Ответ `/v1/route` содержит `trucksil.speedLimits: [{fromIndex, toIndex, kmh, truckKmh?, source:'osm', status:'unverified'}]` — подряд идущие рёбра с одинаковыми значениями сливаются, индексы — точки формы маршрута; рёбра без значения пропускаются (пробел = «неизвестно», а не «без ограничения»); `null` — trace не удался. `trucksil.speedLimitsNote` поясняет происхождение.
- **Полосы.** В запрос `/route` добавлено `turn_lanes: true`; массивы `lanes` Valhalla остаются в `trip.legs[].maneuvers[]` без изменений (новых данных нет). `trucksil.lanes` — только сводка: `maneuversWithLanes`, где искать, `source:'osm'`, `status:'unverified'`.
- **Стоянки / площадки отдыха / АЗС для грузовиков.** Миграция `005_truck_poi.sql` (таблица `truck_poi`, `status` всегда `unverified`), импорт `scripts/import_osm_truck_poi.py`: `amenity=parking` + `hgv=yes|designated` → `parking`; `highway=rest_area` → `rest_area`; `amenity=fuel` + `hgv=yes|designated` → `fuel_hgv` (узлы и линии; линия — среднее её точек; отношения не читаются). Один psql-скрипт в транзакции: `DELETE FROM truck_poi` + вставка (повторяемо). `GET /v1/poi?bbox=&kind=` — только эти три вида, подпись `OSM, unverified`, лицензия ODbL; `trucksil.poiNearRoute` — до 50 ближайших в 500 м от маршрута (`null` — таблицы нет, она пуста или запрос не удался).
- **Фильтр импорта высот (ADR-0016).** `import_osm_maxheight.py` пропускает `highway=service` + `service=parking_aisle|driveway|drive-through`, их проезды под мостами и узлы, лежащие только на таких way (`skipped_service_parking`).
- **Ничего из этого не участвует в проверке безопасности** (ADR-0002): маршрут не строится и не отклоняется по скоростям, полосам или стоянкам. Все данные OSM — ODbL, хранятся только в локальной БД, не коммитятся.

## Последствия
- Водитель (после доработки веб-клиента — отдельный шаг) увидит ограничения скорости, полосы и стоянки с явной пометкой «OSM, не проверено».
- Покрытие `maxspeed:hgv` и `turn:lanes` в Израиле не измерено; пробелы честно остаются пробелами.
- Индексы `speedLimits` относятся к форме из `/trace_attributes` (`edge_walk` той же линии) — совпадают с формой маршрута, пока Valhalla не меняет точки при сопоставлении.
- Стоянки без тега `hgv` (большинство) не попадают — это осознанно: нет данных, что грузовик там поместится.
