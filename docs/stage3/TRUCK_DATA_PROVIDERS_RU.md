# Поставщики грузовых дорожных ограничений: независимая проверка

Проверено 10.10.2026. Продолжение фактического HEAD `bc40773b71f0f89a87f4fbcad6d8b151050c0582`, а не более старого SHA из задания. Пять исследователей и отдельный шестой аудитор; восемь коммерческих поставщиков и пять официальных групп.

## Итог и пределы доказательств

HERE и Trimble явно документируют грузовое покрытие Израиля; MapFactor явно предлагает Truck maps Israel на данных TomTom. Это заявления поставщиков о продукте, не независимое обследование улиц Хайфы. Ни один реальный образец пилота не получен: **NOT TESTED**, 0 новых наборов, 0 подтверждённых ограничений, 0 разрешённых коммерческих импортов. Тестовый ключ, бесплатный тариф и право создавать производную базу — разные условия.

Граница пилота WGS84 (west,south,east,north): `[34.990,32.811,35.004,32.821]`. Граф и OSM-срез не менялись. Carmel Tunnels рассмотрен только как внешний пример; это не Natanzon и не расширение пилота.

C = CONFIRMED, P = PARTIAL, U = UNKNOWN, NL = NOT LICENSED, NS = NOT SUPPORTED, B = BLOCKED. C обозначает документированный объём продукта, а не фактическую проверку данных Хайфы. NL относится к рассмотренным условиям, не невозможности отдельного договора. U не означает отсутствие данных. Для всех строк реальные ограничения пилота, их актуальность и независимые свидетельства: **U**; фактический тест: **NOT TESTED**. Коммерческое право ниже — конкретное право TrucksIL, не наличие платного продукта.

## Сводная матрица

| Поставщик | Грузовые данные Израиля | Атрибуты продукта | Программный доступ продукта | Своя БД/хранение | Коммерческое право TrucksIL |
| --- | --- | --- | --- | --- | --- |
| Yandex | U | U | C | U | U |
| HERE | C | C | C | U | U |
| TomTom | U | C | C | U | U |
| PTV | P | C | C | NL | U |
| Trimble Maps | C | P | C | NL | U |
| Sygic | U | U | C | U | U |
| Mapbox | U | P | C | NL | U |
| MapFactor | C | P | U | U | U |
| Haifa municipality | U | U | P | U | U |
| Israel Ministry of Transport | U | U | U | U | U |
| Netivei Israel | U | U | U | U | U |
| Govmap | U | U | P | NL | NL |
| Carmel Tunnels | U | U | U | U | U |

Yandex consumer Navigator: **NS** в Израиле; коммерческий API отдельно **U**. Официальные ведомства существуют, но это не подтверждение доступного набора truck restrictions: их покрытие в матрице U. Trimble/MapFactor P в атрибутах не означает доступность bulk export. API C может означать только расчёт маршрута/SDK — читайте продуктовую карточку.

## Поля продукта — не заполненность Израиля или Хайфы

C может означать параметр запроса либо документированный вид атрибута. Различие и source IDs сохранены в JSON. **Для каждого из этих полей у каждого поставщика наличие проверенной записи пилота UNKNOWN.** Не преобразовывать null/отсутствие записи в разрешение.

| Поставщик | Высота | Ширина | Длина | Масса | Ось | HGV | Hazmat | Время | Направл. | Повороты | Мост/тоннель | Закрытия |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Yandex | C | C | C | C | C | P | U | U | P | P | U | U |
| HERE | C | C | C | C | C | C | C | C | P | C | C | P |
| TomTom | C | C | C | C | C | C | C | P | P | P | P | C |
| PTV | C | C | C | C | C | C | C | C | C | C | C | U |
| Trimble Maps | P | U | P | P | U | U | U | U | P | P | U | U |
| Sygic | P | P | P | P | U | U | P | U | P | P | P | U |
| Mapbox | C | C | U | C | U | U | U | C | C | C | U | C |
| MapFactor | P | P | P | P | P | U | P | U | P | P | P | U |
| Haifa municipality | U | U | U | U | U | U | U | U | U | U | U | U |
| Israel Ministry of Transport | U | U | U | U | U | U | U | U | U | U | U | U |
| Netivei Israel | U | U | U | U | U | U | U | U | U | U | U | U |
| Govmap | U | U | U | U | U | U | U | U | U | U | U | U |
| Carmel Tunnels | U | U | U | U | U | U | U | U | U | U | U | U |

## Карточки поставщиков и официальные источники

### 1. Yandex

Потребительский truck Navigator NOT SUPPORTED в Израиле: только Россия/Турция. Коммерческий API следует оценивать отдельно; для него Israel UNKNOWN.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://yandex.ru/support/navigator/en/cargo-navigation
- https://www.yandex.ru/support/m-maps/en/cargo-navigation
- https://yandex.com/maps-api/docs/router-api/request.html
- https://yandex.com/maps-api/products/router-api
- https://yandex.ru/legal/maps_api/en/
- https://yandex.com/maps-api/docs/router-api/response.html
- https://yandex.com/maps-api/docs/router-api/examples.html
- https://yandex.com/maps-api/docs/router-api/troubleshooting.html

### 2. HERE

Документация прямо подтверждает Israel truck restrictions с оговоркой о мельчайших дорогах. API возвращает атрибуты; договор/образец пилота не получен. Недельный релиз не доказывает свежесть отдельного знака.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://docs.here.com/routing/docs/routing-v8-truck-routing-coverage
- https://docs.here.com/map-attributes/docs/maps-and-layers
- https://docs.here.com/routing/docs/routing-v8-truck-routing
- https://docs.here.com/map-attributes/reference/map-attributes-api-overview
- https://docs.here.com/tour-planning/docs/country-support
- https://legal.here.com/us-en/terms/here-platform-terms
- https://www.here.com/get-started/pricing/base-plan-restrictions
- https://www.here.com/get-started/pricing/limited-plan-restrictions
- https://docs.here.com/gis-data-suite/docs/gis-data-suite-introduction
- https://www.here.com/contact?intref=dev_docum
- https://www.here.com/get-started/pricing

### 3. TomTom

Israel Calculate Route не равен truck-specific coverage. SnapToRoads содержит maximumDimensions. Текущая таблица Orbis Traffic не содержит Израиль; старый поисковый фрагмент не принимается.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://docs.tomtom.com/routing-api/documentation/tomtom-orbis-maps/v3/product-information/market-coverage
- https://docs.tomtom.com/snap-to-roads-api/documentation/snap-to-roads-api/synchronous-snap-to-roads
- https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v1/product-information/market-coverage
- https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/product-information/market-coverage
- https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route
- https://download.tomtom.com/open/banners/Logistics-product-sheet.pdf
- https://docs.tomtom.com/legal/terms-and-conditions
- https://docs.tomtom.com/pricing
- https://www.tomtom.com/contact-sales/?source_app=docs-portal
- https://help.tomtom.com/hc/en-us/articles/360013901020-About-Truck-navigation
- https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/product-information/market-coverage
- https://docs.tomtom.com/intermediate-traffic-service/documentation/tomtom-orbis-maps/evaluation-api/overview

### 4. PTV

IMEA truck profiles включают IL, но документация предупреждает о различиях атрибутов по странам. Стандартный GLA запрещает компиляцию БД/derivatives если отдельно не согласовано; отдельного соглашения нет.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://developer-applications.myptv.com/CodeSamples/Misc/ProfilesAndCountries.htm
- https://developer.myptv.com/en/documentation/vector-maps-api/concepts/truck-restrictions
- https://developer.myptv.com/en/documentation/routing-api/concepts/truck-restrictions
- https://www.ptvlogistics.com/en/PTV_Logistics_Licensing_Terms_Geodata_EN.pdf?inline=

### 5. Trimble Maps

Независимая загрузка HTML подтвердила green SVG truck-attributes checkbox Israel/ME/Navigable. API расчёта не доказывает массовый экспорт. Blank hazmat не превращён в глобальное NOT SUPPORTED.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://developer.trimblemaps.com/restful-apis/developer-guide/web-services-data-by-country/
- https://developer.trimblemaps.com/restful-apis/routing/introduction/
- https://developer.trimblemaps.com/terms/
- https://transportation.trimble.com/en/legal/customer-terms

### 6. Sygic

Не принимать селектор страны магазина или доступность покупки за покрытие truck restrictions Израиля.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://developers.sygic.com/maps-sdk/
- https://apps.apple.com/us/app/sygic-truck-rv-navigation/id992127700
- https://www.sygic.com/company/eula

### 7. Mapbox

Ограничения vehicle parameters не доказывают truck coverage Хайфы или экспорт её атрибутов. Navigation API storage/extraction forbidden under reviewed standard terms; separate permission required.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://docs.mapbox.com/api/navigation/directions/
- https://www.mapbox.com/legal/product-terms
- https://cdn.prod.website-files.com/609ed46055e27a02ffc0749b/6a60463142f6478d57642594_Mapbox%20Product%20Terms%20(July%2021%2C%202026).pdf
- https://www.mapbox.com/pricing

### 8. MapFactor

Официальный продукт явно перечисляет Israel truck maps; документальное заявление, не измеренное покрытие Хайфы. Данные поставляет TomTom: это не независимое первичное свидетельство и не перенос прав на TomTom API.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://www.mapfactor.com/product/navigator-truck-pro-android/
- https://www.mapfactor.com/product/navigator-truck-pro-ios/

### 9. Haifa municipality

Страница отдела подтверждает подготовку схем движения и утверждение временных схем возле строительных работ. Публикация не является самим приказом. GIS layer35 имеет metadata, но licenseInfo/accessInformation пустые; поле bridge не подтверждает габарит/нагрузку/допуск. Конкретный CleanAir GeoJSON опубликован с ODbL; создание/обновление 27.04.2025. Это граница зоны, не текущие условия въезда по классу грузовика. TIL-HAIFA-001 awaiting_response по существующему реестру; в этой задаче почта не проверялась, новое письмо не отправлено.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://opendata.haifa.muni.il/dataset/clean_air/resource/be774cbd-c4b8-4e40-a50e-344ff3356954
- https://www.haifa.muni.il/development-and-construction/roads-and-traffic/traffic-planning/
- https://gisserver.haifa.muni.il/arcgiswebadaptor/rest/services/PublicSite/Haifa_Eng_Public/MapServer/35/iteminfo

### 10. Israel Ministry of Transport

Hatzav в повторной адресной проверке вернул timeout, cargo-transport 403; обход не выполнялся. Truck survey2017 — исторические потоки по камерам, не дорожные запреты. Heavy-truck — технический реестр автомобилей, не ограничения проезда. Не импортировались. Министерство — канал нормативного регулирования грузовых/опасных перевозок; наличие нормативов не доказывает набор актуальных ограничений конкретной улицы.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://geo.mot.gov.il/
- https://www.gov.il/he/departments/topics/cargo-transport
- https://data.gov.il/he/datasets/ministry_of_transport/truck_survey_2017
- https://data.gov.il/he/datasets/ministry_of_transport/heavy-truck

### 11. Netivei Israel

Официальный поисковый индекс технического задания содержит слой минимальных высот мостов/тоннелей над каждым проездом. Это свидетельство требований к инвентарю, не получение инвентаря или подтверждение покрытия Хайфы. Прямое получение спецификации не удалось (Internal Error). Фактический владелец конкретных городских объектов не установлен.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://www.iroads.co.il/media/12446/נספח-י-להסכם-מפרט-טכני-לאשכולות-א-ו-ב.pdf
- https://www.iroads.co.il/media/bfwpbano/פרק-25-תכנון-גשרים-מבנים-ומנהרות-2026.pdf

### 12. Govmap

На официальном сайте Govmap доступны общие условия: API/сервисы существуют, но права принадлежат владельцам отдельных слоёв. Условия требуют предварительного письменного разрешения для коммерческого/нечастного использования; запрещают сбор слоёв и API без явного разрешения. Прямая страница общих условий gov.il и docs API дали403; текст прочитан в официальном Govmap, а не стороннем пересказе. Не найден лицензированный набор HGV-ограничений пилота; наличие карты/API не доказательство данных.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://www.govmap.gov.il/sites/emergency-services/index.html
- https://www.gov.il/he/pages/gov_terms_of_use
- https://api.govmap.gov.il/docs/

### 13. Carmel Tunnels

Официальная страница на иврите публикует ограничения высоты4.6м, ширины3м и запрет опасных грузов для Carmel Tunnels; также одностороннее движение и запрет U-turn. Английская версия страницы не содержит соответствующего нижнего раздела; вывод взят с ивритской страницы. Это пример опубликованных владельцем параметров в Израиле, но объект вне bbox пилота и не тоннель Natanzon. Значения не импортированы и не перенесены на Natanzon. Дата вступления ограничений в силу и номер приказа не опубликованы на проверенной странице. API и право экспорта не подтверждены.

Официальные источники (проверка 10.10.2026; дата документа/ограничения не предполагается):

- https://www.carmeltunnels.co.il/about-page/בטיחות-במנהרות-הכרמל/
- https://www.carmeltunnels.co.il/en/יצירת-קשר/

## Результаты шести агентов

1. Yandex: consumer только Россия/Турция; коммерческий Israel API отдельно UNKNOWN. Параметры машины не свидетельствуют о выгружаемой базе.
2. HERE: Israel truck restrictions и реальные Map Attributes документированы; мелкие дороги могут не иметь ограничений. Недельная публикация не равна дате обследования знака.
3. TomTom: Calculate Route Israel подтверждён; Snap to Roads возвращает maximumDimensions. Доступность заполненных полей ISR не установлена. Старый поисковый Traffic-фрагмент исправлен после открытия актуальной таблицы от 15.09.2026 без Израиля.
4. Другие: Trimble Israel Truck Attributes подтверждены по HTML/SVG, которые теряются в текстовом парсере; PTV IL profile не гарантирует каждое поле. Sygic country picker исключён как ложное доказательство. MapFactor — TomTom reseller, не независимое первичное свидетельство. Mapbox имеет стандартные ограничения хранения.
5. Официальные: Haifa CleanAir ODbL только граница; Govmap требует письменных прав. Netivei specification требует инвентаря, но сам инвентарь не получен. MOT vehicle register/исторические потоки не дорожные ограничения.
6. Аудитор: отдельно проверены девять критериев каждой строки, исправлены TomTom Traffic и трактовка SVG Trimble. Заключение: документальное покрытие не означает проверенные данные пилота или лицензию производной базы.

## Воспроизводимость и следующий шаг

Полные карточки, источники, вопросы, проверки и отдельный аудит: `data/stage3/truck-data-providers.json`. Права и цены: `PROVIDER_LICENSE_COMPARISON_RU.md`. Адресные неотправленные обращения: `PROVIDER_CONTACT_REQUESTS_RU.md`.

Изменены только исследовательские документы/реестр. `python -m unittest discover -s tests -v`: 72/72 OK, регрессионных исправлений нет. Это проверка существующего кода, не PASS коммерческих данных. CI после публикации отображается в PR2; точный SHA итогового коммита определяется Git, а не самоссылкой внутри коммита.

Следующий разрешённый этап — подготовленные запросы HERE/Trimble после отдельного разрешения на отправку, затем TomTom/PTV. До импорта нужны бесплатный разрешённый образец bbox, письменные права хранения/переработки/распространения, источник и дата каждой записи, независимое сравнение с текущими приказами/знаками. Обращение TIL-HAIFA-001 не дублируется. Согласованные лицензии не означают подтверждённую безопасность маршрута.
