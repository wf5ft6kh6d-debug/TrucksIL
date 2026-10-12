# Этап 6: доказательства ограничений и исследовательская маршрутизация

База: bcec3526862ed5c02e4ee3e58841e54d9937f883, stage5/truck-rules-research-20261012.
Продолжение: stage6/restriction-evidence-routing-20261012.
Проверка 2026-10-12: продолжения не обнаружено; PR №5 остаётся Draft, оба CI базы SUCCESS.

До изменений выделены отдельные detached worktree и непересекающиеся файлы:

| Направление | Владелец | Файлы |
|---|---|---|
| Временные утверждения и первоисточники | barriers | scripts/stage6/claims.py, tests/test_stage6_claims.py, docs/stage6/TEMPORAL_EVIDENCE_RU.md |
| Пробелы доказательств мостов | bridges | scripts/stage6/bridge_gaps.py, tests/test_stage6_bridge_gaps.py, docs/stage6/BRIDGE_EVIDENCE_RU.md |
| История поворотов | temporal | scripts/stage6/routing.py, tests/test_stage6_routing.py, docs/stage6/ROUTING_RU.md |
| Независимый эталон и национальный эксперимент | scenarios | scripts/stage6/validation.py, scripts/stage6/national.py, tests/test_stage6_validation.py, tests/fixtures/stage6/, docs/stage6/NATIONAL_VALIDATION_RU.md |
| Общие интерфейсы, БД и CI | integration | scripts/stage6/contract.py, postgis.py, run_research.py, __init__.py; data/stage6/; tests/test_stage6_contract.py, test_stage6_postgis.py; workflow этапа 6 и inherited trigger; docs/stage6/INTEGRATION_RU.md; дополнение docs/stage5/INDEPENDENT_AUDIT_RU.md |
| Независимый аудит | auditor | docs/stage6/INDEPENDENT_AUDIT_RU.md; собственные проверяющие программы вне репозитория |
| Координация и публикация | root | этот план, журнал, итоговая приёмка; перенос согласованных файлов и коммиты |

Только integration меняет общие интерфейсы. Только root создаёт коммиты и публикует новую ветку/отдельный Draft PR. Старые ветки и PR, исходные графы и пилот Хайфы не изменяются.

965 нормализованных исторических записей используются повторно без повторного импорта XLSX. Оригинальный пользовательский текст и реестры частных строк хранятся отдельно и не входят в Git/CI. Публичные fixtures явно синтетические. Пользовательское свидетельство не заменяет официальное доказательство. VERIFIED не является целевым количеством.

Приёмка раздельна: техническая обработка, доказанность действующих ограничений, покрытие исследовательской маршрутизации. Обязательны все 260 унаследованных тестов и новые регрессии, независимый аудит, изолированный PostgreSQL/PostGIS, повторный импорт, rollback, воспроизводимость и CI точного итогового SHA. Национальный эксперимент ограничивается заранее объявленными бюджетами; превышение означает незавершённый результат с причиной. Неизвестность не означает разрешение.
