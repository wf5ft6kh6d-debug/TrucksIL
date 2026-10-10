# Официальные свидетельства инфраструктуры — 10.10.2026

HEAD до начала работы: 4fa8498bd5debe2e89d3a5ab6a791e842696a82c, подтверждён
GitHub. Использованы сохранённые raw/topology/history; новые OSM-наборы не
скачивались. Граф, bbox, SHA-256 исходного среза и 72 теста сохранены.

## Ответ муниципалитета

Подключённый Outlook проверен: прямой отправитель Rasha@haifa.muni.il,
муниципальный домен, TrucksIL и TIL-HAIFA-001 с 10.10.2026. Найдены исходящее
обращение и копия владельцу, но ответ муниципалитета в результатах не обнаружен;
страниц продолжения поиска нет. response_status=awaiting_response.
Получение муниципалитетом и регистрационный номер не подтверждены. Возможна
задержка индексации/другая тема или отправитель; отсутствие результата не доказывает
отсутствие письма во всех системах. В Git нет исходного письма, приватных ID,
адреса владельца или вложений. Ничего не отправлялось.

## Восемь пересечений

Во всех случаях геометрическое пересечение внутреннее, DE-9IM 0F1FF0102,
общих node ID нет; crossing_osm_node_id=null. Точка пересечения вычислена,
это не новый OSM node. Функция дороги в таблице — OSM-наблюдение, не официальное
разрешение транспорта. Полные версии, timestamps, tags (включая отсутствующие
bridge/tunnel/layer/level) и последовательности nodes — в JSON.

| OSM ways | Поддерживающие node pairs | WGS84 (lon,lat) | OSM функция | Статус |
|---|---|---|---|---|
| 200730597 / 1053293268 | [9679759617, 8890952032] / [1999155667, 9679759622] | [35.0017197088284, 32.815429709781405] | tertiary / footway | UNKNOWN |
| 355094019 / 731754156 | [9679759627, 9835971652] / [6852518467, 9835971651] | [35.002519006086665, 32.81588943712989] | footway / residential | UNKNOWN |
| 1053293255 / 1053293268 | [1343200970, 2106948806] / [1999155667, 9679759622] | [35.00155670452429, 32.815356007953476] | tertiary / footway | UNKNOWN |
| 1053293259 / 1053293268 | [9679759595, 9679759596] / [1999155667, 9679759622] | [35.00143278466444, 32.81529997802079] | service / footway | UNKNOWN |
| 1053293264 / 1053293268 | [9679759612, 9679759611] / [1999155667, 9679759622] | [35.00150399304648, 32.81533217464252] | footway / footway | UNKNOWN |
| 1053293265 / 1053293268 | [2106948806, 9679759588] / [1999155667, 9679759622] | [35.001591994484976, 32.8153719641862] | service / footway | UNKNOWN |
| 1053293268 / 1053293275 | [1999155667, 9679759622] / [9679759615, 2106948797] | [35.001619868865966, 32.8153845674904] | footway / service | UNKNOWN |
| 1053293268 / 1071935639 | [1999155667, 9679759622] / [9835971662, 3606996326] | [35.001772305171755, 32.815453491034724] | footway / footway | UNKNOWN |

У моста 1053293268 bridge=yes/layer=1; у Natanzon 731754156 tunnel=yes/layer=-1.
У другой стороны каждого пересечения layer отсутствует; level не задаёт
независимого подтверждения. Физическое соединение, фактические уровни и текущий
допуск грузовиков UNKNOWN. Семь мостовых случаев имеют исторический кандидат
свидетельства ниже; точное соответствие современному asset ID не установлено.
Один тоннельный случай не имеет официального чертежа. Статус навигационного
использования всех случаев QUARANTINE; граф не меняется.

## Официальные источники и пределы свидетельств

- **HAIFA-BRIDGE-AUDIT-2016** — [Haifa Municipality audit](https://www.haifa.muni.il/wp-content/uploads/2021/08/%D7%98%D7%99%D7%A4%D7%95%D7%9C-%D7%94%D7%A2%D7%99%D7%A8%D7%99%D7%99%D7%94-%D7%91%D7%92%D7%A9%D7%A8%D7%99%D7%9D-%D7%95%D7%91%D7%9E%D7%91%D7%A0%D7%99-%D7%93%D7%A8%D7%9A.pdf). Read PDF and visually checked page 19 (zero-based 18). Historical pedestrian bridge between courthouse and government complex above PalYam; no current georeferenced structure ID or numeric clearance established. Статус: `historical_candidate`; права повторного использования: unknown.
- **HAIFA-GIS-35** — [Haifa Municipality GIS](https://gisserver.haifa.muni.il/arcgiswebadaptor/rest/services/PublicSite/Haifa_Eng_Public/MapServer/35). Public polyline layer metadata: EPSG:2039, HasZ=false; bridge/passage symbols. Fields OBJECTID/Shape/LAYER/Shape_Length do not establish current physical elevation, clearances or validity. Bbox count request returned fetch Internal Error, not a zero count. Статус: `metadata_only`; права повторного использования: unknown.
- **HAIFA-GIS-35-LICENSE** — [Haifa Municipality GIS](https://gisserver.haifa.muni.il/arcgiswebadaptor/rest/services/PublicSite/Haifa_Eng_Public/MapServer/35/iteminfo). licenseInfo and accessInformation are blank. Public access is not a confirmed dataset reuse grant. Статус: `rights_unknown`; права повторного использования: unknown.
- **HAIFA-TRAFFIC** — [Haifa Municipality Traffic Planning](https://www.haifa.muni.il/development-and-construction/roads-and-traffic/traffic-planning/). Published competence for traffic plans and public contact Rasha@haifa.muni.il; not an approved plan or order. Статус: `contact_only`; права повторного использования: unknown.
- **HAIFA-ROAD-PLANNING** — [Haifa Municipality Road Planning](https://www.haifa.muni.il/development-and-construction/roads-and-traffic/road-planning/). Published professional channel for road planning/heights approval; asset ownership for these objects remains unconfirmed. Статус: `contact_only`; права повторного использования: unknown.
- **MOT-LEVELSEPARATION** — [Ministry of Transport](https://data.gov.il/he/datasets/ministry_of_transport/levelseparation/58612e24-148a-443a-932a-e4d695396535). Search index exposes rail/road grade-separation resource. Direct fetch 403 Forbidden; pilot coverage, current edition and rights not verified. No data downloaded. Статус: `access_blocked`; права повторного использования: unknown.
- **MOT-HATZAV** — [Ministry of Transport](https://geo.mot.gov.il/). Direct fetch timeout. Indexed portal provides geo@mot.gov.il and states planning information is not binding; no site-specific layer obtained. Статус: `access_blocked`; права повторного использования: unknown.
- **MOT-SAFETY-SPEC** — [Ministry of Transport](https://www.gov.il/BlobFolder/generalpage/30_12_2025/he/%D7%9E%D7%A4%D7%A8%D7%98%20%D7%A9%D7%9B%D7%91%D7%95%D7%AA%20%D7%94%D7%A1%D7%93%D7%A8%D7%99%20%D7%91%D7%98%D7%99%D7%97%D7%95%D7%AA%20%D7%91%D7%AA%D7%A9%D7%AA%D7%99%D7%AA%20%D7%93%D7%A8%D7%9B%D7%99%D7%9D%202.pdf). Indexed GIS safety-layer specification, not a site-specific dataset. Direct PDF fetch 403 Forbidden; not accepted as restriction evidence. Статус: `access_blocked`; права повторного использования: unknown.
- **IROADS-SIGNALS-2019** — [Netivei Israel](https://www.iroads.co.il/media/14215/%D7%A0%D7%A1%D7%A4%D7%97_%D7%96-%D7%9C%D7%9E%D7%A4%D7%A8%D7%98-%D7%94%D7%9E%D7%99%D7%95%D7%97%D7%93-_-%D7%A8%D7%9E%D7%96%D7%95%D7%A8%D7%99%D7%9D_%D7%9B%D7%95%D7%9C%D7%9C_%D7%94%D7%A2%D7%93%D7%A4%D7%94.pdf). Indexed signal-maintenance annex mentions Natanzon/PalYam. Direct PDF fetch 403 Forbidden; no current order, tunnel plan or competence over asset proven. Статус: `access_blocked`; права повторного использования: unknown.
- **HAIFA-LIGHTING-2025** — [Haifa Municipality](https://www2.haifa.muni.il/Michrazim/TendersFiles/42-2025First.pdf). Search match is street lighting inventory, not Natanzon tunnel clearance or a traffic restriction. Rejected for parameter verification. Статус: `not_applicable`; права повторного использования: unknown.

Муниципальный мостовой отчёт: аудит февраля–марта 2016, обследование описанного
моста ноября 2014, PDF страница 19 (индекс 18). Дата 2021/08 в URL не означает
дату обследования. Документ не подтверждает состояние в 2026; старое отсутствие
знака не означает нынешнее разрешение. Числовые высоты других объектов из отчёта
не перенесены на Natanzon или мост пилота. Описание местоположения — основание
для адресного запроса, не VERIFIED соответствие восьми точкам.

GIS layer35: EPSG:2039, HasZ=false; наличие класса «мост» в легенде не доказывает
наличие/уровень объекта в пилоте. licenseInfo пустое, явного разрешения нет.
Bbox count запрос вернул ошибку получения, а не ноль объектов. Не обходились
403 для data.gov.il/Netivei/спецификации; Hatzav вернул timeout.
Официальных текущих планов/приказов для трёх тоннелей не получено.

Новых подтверждённых лицензий нет. OSM ODbL-1.0 сохранена. Ни один официальный
набор не импортирован. Оригиналы официальных файлов не сохранялись без
подтверждения прав; sha256=null с причиной в реестре, не выдуманный checksum.
Сохранённые собственные реестры — исследовательские метаданные и ссылки.

## Воспроизводимое сопоставление и ручная приёмка

1. `python scripts/stage3/build_infrastructure_evidence.py /tmp/infrastructure-evidence.json`.
   Загружаются проверенный raw manifest и topology-audit, точным целочисленным
   алгоритмом определяются две пары nodes каждого crossing; выход содержит
   исходные IDs/versions/timestamps/tags, координаты и checksum provenance.
2. `cmp data/stage3/infrastructure-evidence.json /tmp/infrastructure-evidence.json`.
   CI повторяет генерацию и сравнение байтов; это воспроизводит реестр, не
   превращает кандидата официального источника в доказательство.
3. После ответа пройти OFFICIAL_DOCUMENT_INTAKE_RU.md. Подтвердить издателя,
   компетенцию, номер/подпись, дату, отмены и право хранения/переработки каждого
   документа. Без этого источник остаётся quarantine, исходный файл приватен.
4. Для каждого параметра отдельно сопоставить оригинальную CRS, точность,
   участок и направление; получить текущий asset ID, инженерные отметки,
   геометрию физических въездов/съездов, единицы, классы ТС и срок действия.
   Близость к OSM way — только кандидат соответствия. Не угадывать отметку из layer.
5. Второй проверяющий повторяет сопоставление по оригиналу и независимому
   официальному каналу. CONFLICT при противоречии; UNKNOWN при нехватке данных;
   OUT_OF_SCOPE для координат вне bbox; QUARANTINE для непригодных к навигации
   сведений. VERIFIED только для конкретного независимо подтверждённого утверждения.
6. Отдельно подготовить staging-кандидат по действующему контракту, выполнить
   валидатор и PostgreSQL/PostGIS в изолированной БД. Импорт/правка графа/выход
   в навигацию не следуют автоматически из приёмки документа.

Здесь новые правила продвижения в VERIFIED не реализованы. Скрипт только
воспроизводит текущий UNKNOWN-реестр; официальных входных документов ещё нет.
Предположений о направлениях, порталах, грузовых ограничениях не добавлено.

## Дополнительный запрос

Подготовлен TIL-HAIFA-003 в requests/INFRASTRUCTURE_SUPPLEMENT_HE_RU.md:
восемь координат/OSM pairs, три тоннеля/шесть endpoint IDs, просьба о текущих
планах/разрезах/asset IDs, габаритах и лицензиях. Адресат — отдел планирования
движения с просьбой передать компетентным GIS/инженерным службам. **draft_not_sent**;
новое разрешение пользователя обязательно. TIL-HAIFA-002 остаётся резервным.

Технические проверки и независимые движки повторяются в полном CI после коммита;
фактические SHA/run/conclusion — в Draft PR №2 и финальном отчёте.
