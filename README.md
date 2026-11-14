# TrucksIL

> **Статус: ранний прототип. НЕ использовать для реальной навигации.**
> **Status: early prototype. NOT for real navigation.**

## Русский

TrucksIL — приложение для построения маршрутов грузовиков в Израиле с учётом габаритов и массы ТС, ограничений по высоте, весу и запретов движения. Приоритет — безопасность: маршрут строится только по проверенным данным, а при сомнениях пользователь получает предупреждение.

Сейчас в репозитории только документация, черновые JSON-схемы и примеры. Кода приложения пока нет.

## English

TrucksIL is a truck routing app for Israel that takes vehicle dimensions and weight, height/weight limits and truck bans into account. Safety comes first: routes rely only on verified data, and uncertainty is surfaced to the driver.

The repository currently contains documentation, draft JSON schemas and examples only. There is no application code yet.

## Структура / Structure

| Путь / Path | Содержимое / Contents |
|---|---|
| `docs/` | Требования, архитектура, план, политика данных / Requirements, architecture, roadmap, data policy |
| `data/` | JSON-схемы и данные об ограничениях / Restriction schemas and data |
| `src/` | Исходный код и примеры (профиль ТС) / Source code and examples (vehicle profile) |
| `index.html` | Статическая страница-заглушка / Static placeholder page |

## Документация / Documentation

- [docs/README.md](docs/README.md) — обзор / overview
- [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md) — требования / product requirements
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура / architecture
- [docs/DATA_VERIFICATION.md](docs/DATA_VERIFICATION.md) — верификация данных / data verification policy
- [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) — источники данных / data sources
- [docs/ROADMAP.md](docs/ROADMAP.md) — статус и план / status and roadmap
- [CONTRIBUTING.md](CONTRIBUTING.md) — как участвовать / how to contribute

## Проверка схем / Schema validation

Требуется Node.js / Requires Node.js:

```sh
npm install
npm test
```

`npm test` проверяет JSON-схемы и примеры. / `npm test` validates the JSON schemas and examples.

## Лицензия / License

Лицензия ещё не выбрана. / No license has been chosen yet.
