# Обзор навигаторов (2025–2026) и что из этого взять в TrucksIL

_Дата: 2026-11-21. Статус: исследование, не решение. Решения оформлять отдельными ADR._

Обозначения: **[✓]** подтверждено источником из списка ниже; **[?]** по общим сведениям / документации прошлых лет, в этом исследовании не перепроверено — перед использованием в решениях проверить.

## 1. Сводная таблица

Легенда: ✔ есть, ~ частично/ограниченно, — нет, ? не проверено.

| Навигатор | Профиль ТС (В/Ш/Д/масса/ось) | ADR/тоннели | Временные окна | Полосы | Камеры | Сообщения сообщества | Офлайн | Стоянки грузовиков | HOS/время за рулём | Трафик | Android Auto/CarPlay | Карты / движок |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Waze | — (нет грузового режима) [?] | — | — | ~ | ✔ | ✔ (ядро продукта) | — | — | — | собственный краудсорсинг | ✔/✔ | собственная карта (редакторы) |
| Яндекс Навигатор | ✔ грузовик: масса, габариты [✓] | ? | ? | ✔ | ✔ | ✔ дорожные события | ~ | ? | — | Яндекс.Пробки | ~ | Яндекс; в Израиле покрытие [?] |
| Google Maps | приложение — нет; Platform: Large Vehicle Routing GA (08.2026) [✓] | ? | ? | ✔ | ✔ | ~ | ✔ | — | — | Google | ✔/✔ | Google, проприетарно |
| iGO Navigation (Truck) | ✔ [?] | ✔ [?] | ? | ✔ | ✔ | — | ✔ | ~ | — | TMC/платно | ? | HERE/TomTom [?] |
| Sygic Truck & Caravan | ✔ вкл. ось, прицепы [✓] | ✔ коды тоннелей ADR [✓] | ✔ городские ограничения по времени [✓] | ✔ | ✔ | ~ | ✔ | ✔ | ? | TomTom [?] | ✔/✔ [?] | TomTom/ собственная надстройка [?] |
| TomTom GO Expert | ✔ | ✔ ADR [?] | ✔ [?] | ✔ | ✔ | ~ | ✔ | ✔ | — | TomTom Traffic | ✔/✔ [?] | TomTom |
| Garmin dēzl | ✔ | ✔ [?] | ✔ [?] | ✔ | ✔ | ✔ (отчёты водителей) [?] | ✔ (устройство) | ✔ (Trucker Path POI) [?] | ✔ HOS-напоминания [?] | Garmin/ HERE [?] | ✔ [?] | HERE [?] |
| HERE WeGo / HERE Routing v8 | API: currentWeight, grossWeight, height, weightPerAxle… [✓]; приложение — нет грузовика [?] | ✔ tunnelCategory, shippedHazardousGoods [?] | ✔ (time-dependent) [?] | ✔ | ✔ | — | ✔ | API | — | HERE Traffic | ✔ [?] | HERE, проприетарно |
| CoPilot (Trimble) | ✔ | ✔ | ✔ | ✔ | ? | — | ✔ | ✔ | ✔ (ELD-интеграции) [?] | Trimble/ партнёры | ✔ [?] | Trimble PC*MILER [?] |
| Trucker Path | ✔ [?] | ~ | — | ? | — | ✔ (стоянки, весы) [?] | ? | ✔ ядро продукта | ~ | ? | ? | США/Канада |
| Hammer | ✔ [?] | ? | — | ~ | ? | ✔ [?] | — | ✔ | ? | ? | ✔ AA [?] | США; Google basemap [?] |
| OsmAnd | ✔ высота, ширина, масса, нагрузка на ось, масса при полной загрузке [✓] | ✔ hazmat [✓]; категории тоннелей [?] | ~ (OSM conditional) [?] | ✔ из turn:lanes [?] | ✔ OSM | — | ✔ | ~ OSM | — | — | ✔/✔ [?] | OSM, собственный движок, открытый код (GPLv3) |
| Organic Maps | — (нет грузового профиля) [?] | — | — | ✔ | ✔ | — | ✔ | — | — | — | ✔/✔ [?] | OSM, открытый код |
| Magic Earth | — (авто/вело/пешком) [✓ сайт не упоминает грузовик] | — | — | ✔ | ✔ | ~ | ✔ [✓] | — | — | ✔ [✓] | CarPlay ✔ [✓] | OSM-based [?] |

Ключевые наблюдения:
- Полноценные грузовые функции (ADR-тоннели, оси, временные окна, HOS) — только у платных проприетарных продуктов на картах HERE/TomTom/Trimble. Их данные лицензировать нам невыгодно и не нужно.
- В открытом мире: OsmAnd (клиент) и Valhalla/GraphHopper (движки) покрывают габариты, массу, hazmat из OSM-тегов.
- Израиль-специфичного грузового навигатора с верифицированными ограничениями нет — это наша ниша [?, на основании отсутствия находок].
- Google Large Vehicle Routing (GA 17.08.2026) — B2B API, не потребительская функция Google Maps [✓ FreightWaves].

## 2. Наш выбор (приоритет)

Принцип ADR-0002: всё ниже только усиливает предупреждения или ограничения; ни одна функция не «разрешает» участок без verified-данных.

| # | Функция | Почему | Усилия | Зависимости / лицензии | Этап ROADMAP | Конкретный следующий шаг |
|---|---|---|---|---|---|---|
| 1 | Полный грузовой профиль в Valhalla (height, width, length, weight, axle_load, axle_count, hazmat) + наши ограничения как исключения | Ядро безопасности, уже совпадает с US-01/US-02 | M | Valhalla (MIT), OSM (ODbL) | 3 | Сопоставить `vehicle-profile.schema.json` с truck costing; `hgv_no_access_penalty`=43200 (запрет по умолчанию) [✓]; наши verified-ограничения подавать через `exclude_polygons`/кастомные теги на сборке тайлов; регрессионные тесты на известных низких мостах |
| 2 | ADR/hazmat и тоннели | Израиль: опасные грузы, тоннели (Кармель, Шаар ха-Гай и др.) | M | OSM `hazmat=*`, `hazmat:adr_tunnel_category`/`tunnel:category` [?], источник — правила Минтранса | 3 | Проверить в 3.9.2 поддержку `hazmat` (сейчас boolean [✓]); кодов тоннелей в Valhalla нет [? проверить] → хранить категорию в PostGIS и исключать рёбра сами; собрать список тоннелей Израиля с категориями как restriction с verified/unverified |
| 3 | Явная «зона неизвестности» на маршруте | Отличие от всех конкурентов: они молчат, когда данных нет | S–M | Наши данные | 3–4 | Уже в US-03; визуализировать в MapLibre отдельным слоем |
| 4 | Офлайн-карта Израиля в PMTiles + кеш маршрута в PWA | Мёртвые зоны (Негев, Арава), ограничения PWA | M | Protomaps / planetiler (OSM, ODbL; атрибуция) [✓] | 4 | Сгенерировать israel.pmtiles (~ сотни МБ [?]), протокол `pmtiles://` в MapLibre [✓], service worker + Cache Storage; RTL-плагин для he/ar [✓ пример Protomaps] |
| 5 | Голосовые подсказки | Безопасность за рулём | M | Valhalla narrative (языки: he, ru, ar, en — [? проверить he/ar]); Web Speech API (голоса зависят от ОС) | 4 | Прототип: `directions_type=instructions`, `language`; проверить качество TTS на иврите/арабском на Android; при плохом — предзаписанные фразы |
| 6 | Отслеживание маршрута и пересчёт при отклонении | Базовая навигация | M | MapLibre GL JS; Valhalla `/trace_attributes`/map-matching | 4 | Свой лёгкий модуль (map-matching на клиенте + перерасчёт); MapLibre Navigation SDK только для нативных iOS/Android [✓] — для PWA не годится |
| 7 | Отчёты водителей (ограничение/ремонт/полиция-весы) с TTL и голосами | Аналог сообществ Waze/Trucker Path, но только как предупреждение | M | Свои данные; ADR-0012 | 5 | Уже спроектировано; добавить тип «низкий мост/знак не совпадает с картой» как вход для верификации |
| 8 | Лента дорожных работ/закрытий из официальных источников | Израиль: закрытия Нетивей Исраэль, муниципалитеты | M | Waze for Cities (партнёрская программа, данные в обмен на данные; условия — договор) [✓ существование, условия ?]; data.gov.il [?]; Нетивей Исраэль — открытого API не найдено [?] | 5 | Подать заявку в Waze for Cities как data partner; запросить у Нетивей Исраэль/Аялон условия; до лицензии — не использовать (как ADR-0007) |
| 9 | Ограничения скорости и предупреждение о превышении | Для грузовиков в Израиле отдельные лимиты | S | OSM `maxspeed`, `maxspeed:hgv` [?]; правила ПДД Израиля | 4 | Отображать `maxspeed:hgv` > `maxspeed` > «неизвестно»; не выдавать дефолт как факт; Valhalla `top_speed` для ETA |
| 10 | Подсказки по полосам | Сложные развязки (Аялон, Гломы) | S–M | OSM `turn:lanes` (покрытие в Израиле ? — проверить запросом Overpass) | 4 | Валхалла возвращает lane-информацию в маневрах [?]; рисовать стрелки собственным компонентом |
| 11 | Стоянки грузовиков / места отдыха | Израиль: ограниченная ночная стоянка | S | OSM `amenity=parking` + `hgv=designated/yes`, `highway=rest_area`, `amenity=fuel`+`hgv=yes` [?] | 5 | Выгрузка Overpass → PostGIS → слой с пометкой «из OSM, не проверено» |
| 12 | Таймер смены (напоминание о перерыве) | Есть в PRD как вспомогательная функция; без «сертификации» | S | Правила часов работы водителей Израиля [?] | 5–6 | Только напоминание, без юридических утверждений (PRD, принцип 6) |

Не приоритетно / позже: time-dependent маршрутизация Valhalla (`date_time`) с условными ограничениями OSM `*:conditional` (полезно для запретов въезда грузовиков в часы пик в городах, но зависит от качества данных) — этап 5+, усилия M. Сравнение с GraphHopper/OSRM не требуется: OSRM не поддерживает динамические габариты на запрос, GraphHopper — возможен, но выбор Valhalla уже зафиксирован ADR-0009.

## 3. Чего НЕ делать

| Что | Почему |
|---|---|
| Брать данные/тайлы Google, HERE, TomTom, Yandex, Waze (скрейпинг, кеширование) | Проприетарные лицензии, ToS запрещают; несовместимо с ODbL-производными |
| Лицензировать HERE/TomTom truck attributes | Дорого для малой команды; покрытие Израиля не гарантировано [?] |
| Google Large Vehicle Routing как основной движок | Платный API, нельзя смешивать с нашими ограничениями и показывать на не-Google карте [? проверить ToS] |
| Копировать UI, иконки, звуки, названия функций конкурентов (включая стиль «Waze-предупреждений») | Товарные знаки и авторское право |
| Краудсорсинговые сообщения как основание «проехать можно» | Нарушает ADR-0002 |
| Полицейские посты/антирадар как функция | Юридический риск в Израиле [? проверить]; не относится к безопасности груза |
| HOS/ELD-сертификация | PRD: без юридической сертификации; американская модель не применима |
| MapLibre Navigation SDK (Android/iOS) в PWA | Нативные SDK, не для веба [✓] |
| Офлайн-маршрутизация на клиенте (Valhalla в WASM) сейчас | Высокая сложность; кеша маршрута достаточно для MVP |
| Код OsmAnd | GPLv3 — несовместимо, если наша лицензия иная (см. ADR-0010); брать только идеи |

## 4. Источники (доступ 2026-11-21)

1. Valhalla API reference — truck costing options, hazmat, hgv_no_access_penalty, exclude_tunnels — https://valhalla.github.io/valhalla/api/route/api-reference/
2. Valhalla issue #4401 «Hazmat ignored for truck routing» — https://github.com/valhalla/valhalla/issues/4401
3. Sygic: Routing options & technology (ADR tunnel codes, оси, временные ограничения) — https://enterprise.sygic.com/professional-gps-navigation-sdk/routing-options-technology
4. Sygic Professional Navigation 28.0, Truck warnings — https://www.manula.com/manuals/sygic/sygic-professional-navigation/28.0/en/topic/truck-warnings
5. Sygic Truck & Caravan user guide — https://help.sygic.com/hc/en-us/articles/37948287320338-User-guide-for-Sygic-Truck-Caravan-Navigation
6. Яндекс Навигатор: настройка грузового режима — https://yandex.com.tr/support/navigator/en/cargo-navigation
7. Яндекс Карты: настройки маршрута для авто и грузовиков — https://yandex.com/support/m-maps/en/navigation-settings
8. Google Maps Platform, Large Vehicle Routing — https://mapsplatform.google.com/resources/blog/introducing-large-vehicle-routing-address-the-unique-logistics-needs-of-large-vehicle-fleets/
9. FreightWaves, о GA Large Vehicle Routing (17.08.2026) — https://www.freightwaves.com/news/google-maps-just-launched-truck-aware-routing-that-knows-about-low-bridges-and-weight-limits-here-is-what-it-means-and-what-it-does-not
10. HERE Routing v8, Truck routing — https://docs.here.com/routing/docs/routing-v8-truck-routing
11. OsmAnd: Car/Truck routing parameters — https://osmand.net/docs/user/navigation/routing/car-based-routing/
12. Magic Earth — https://www.magicearth.com/
13. Organic Maps — https://organicmaps.app/
14. MapLibre turn-by-turn navigation discussion #210 — https://github.com/maplibre/maplibre/discussions/210
15. Make with MapLibre: routing — https://makewithmaplibre.com/routing/
16. MapLibre Navigation Android v2 — https://maplibre.org/news/2023-03-27-android-navigation-version-2/
17. Protomaps: PMTiles for MapLibre — https://docs.protomaps.com/pmtiles/maplibre
18. Protomaps: Security & privacy (пример с RTL-плагином) — https://docs.protomaps.com/guide/security-privacy
19. Waze for Cities — https://www.waze.com/partners/wazeforcities
20. Waze for Cities data-sharing tools — https://support.google.com/waze/partners/answer/10618047?hl=en

Не найдено открытого API трафика/закрытий Нетивей Исраэль и Аялон — требуется прямой запрос. Данные по iGO, TomTom, Garmin, CoPilot, Trucker Path, Hammer в этой итерации не перепроверялись (помечены [?]).
