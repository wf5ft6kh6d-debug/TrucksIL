# Покрытие OSM: ограничения для грузовиков (Израиль)

> **Статус: измерение НЕ выполнено.** В среде, где готовился документ, исходящий
> доступ к `download.geofabrik.de`, `overpass-api.de` и зеркалам Overpass
> (kumi.systems, mail.ru, private.coffee) и к `planet.openstreetmap.org` был
> заблокирован прокси (CONNECT 403). Таблицы ниже — шаблон; заполните их,
> запустив скрипт локально.

## Данные

- Источник: Geofabrik, `asia/israel-and-palestine-latest.osm.pbf`
  (покрывает Израиль, Западный берег и Газу).
- Дата данных: _заполнить_ — поле `max_object_timestamp_utc` из вывода скрипта
  (≈ момент среза) или `osmium fileinfo -e`.

## Метод

```
pip install osmium
python3 scripts/osm_coverage.py israel-and-palestine-latest.osm.pbf > osm_stats.json
```

Скрипт (`scripts/osm_coverage.py`) выводит только агрегаты:

- учитываются way с `highway=*`, кроме пешеходных/вело/строящихся;
  `*_link` относятся к родительскому классу;
- счётчики тегов для way и node: `maxheight`, `maxheight:physical`, `maxwidth`,
  `maxlength`, `maxweight`, `maxaxleload`, `hgv`, `hazmat`;
- `bridge`/`tunnel`/`covered` (≠ `no`) на дорогах: всего и сколько из них имеют
  `maxheight` или `maxheight:physical`;
- разбор `maxheight`: метры, число без единицы, футы/дюймы (`14'6"`), `ft`,
  нечисловые (`default`, `none`, `below_default`…); корзины < 2 м … > 7 м.

Ограничения метода:

- `maxheight` на way-мосте относится к проезду **по** мосту; габарит **под**
  мостом ставится на нижнюю дорогу (или на node). Скрипт не делает
  геометрического сопоставления «мост → дорога под ним», поэтому доля мостов с
  `maxheight` — нижняя оценка полезного покрытия. Для туннелей и `covered`
  оценка корректна.
- Разделение Израиль / Западный берег / Газа — по первой точке way и грубым
  полигонам в скрипте. Это не юридическая граница; Иерусалим и шовная зона
  классифицируются неточно. Использовать только для порядка величин.

## Результаты (заполнить)

| Показатель | Значение |
|---|---|
| Дорожных way всего | |
| way с `maxheight` / `maxheight:physical` | |
| node с `maxheight` | |
| Мостов (bridge) / из них с maxheight | |
| Туннелей (tunnel) / из них с maxheight | |
| covered / из них с maxheight | |

| Класс | way | с maxheight |
|---|---|---|
| motorway | | |
| trunk | | |
| primary | | |
| secondary | | |
| tertiary | | |
| residential | | |
| other | | |

| Тег | way | node |
|---|---|---|
| maxwidth / maxlength / maxweight / maxaxleload / hgv / hazmat | | |

Распределение `maxheight`: единицы, нечисловые значения, выбросы (< 2 м,
> 7 м) — из полей `maxheight_units`, `maxheight_non_numeric`,
`maxheight_buckets_m`.

## Выводы для TrucksIL

- Значения из OSM — только **кандидаты** (`status: candidate`). Без подтверждения
  знаком или официальным источником `valueSource` = `unknown`; `sign` —
  только если известно, что значение снято со знака (например, есть
  `source:maxheight=sign` или фото/обход).
- Нечисловые значения (`default`, `none`, `below_default`) не дают габарита и
  не должны превращаться в число.
- Выбросы (< 2 м, > 7 м) и значения в футах — отдельная проверка перед импортом.
- Отсутствие тега ≠ отсутствие ограничения; маршрутизация не должна считать
  мост без `maxheight` безопасным.

## Лицензия (ODbL)

Данные © участники OpenStreetMap, лицензия ODbL 1.0. Требуется атрибуция
«© OpenStreetMap contributors» с ссылкой на openstreetmap.org/copyright.
Если мы публикуем или используем публично базу, производную от OSM
(например, импорт ограничений вместе с нашими данными), действует share-alike:
производная база должна быть доступна под ODbL. Поэтому сырые данные OSM в
репозиторий не копируются; здесь — только агрегаты.
