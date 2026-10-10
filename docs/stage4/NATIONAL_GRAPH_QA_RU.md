# Национальный граф: техническая приёмка

Сохранены72прежних теста. Добавлены19тестов правил направлений, геометрии,
категорий, provenance и масштабирования DSU; синтетические случаи только в tests.
Локально91/91тестPASS с национальными зависимостями. Полный национальный CI SUCCESS: https://github.com/wf5ft6kh6d-debug/TrucksIL/actions/runs/38051002438 (код6125b35272170a86e7950da4027c1b1e48a3eb2d).
Ни один результат поставщика/OSM не объявляется verified.

Команды:
```
python -m unittest discover -s tests -v
python scripts/compare_schema_engine.py
python scripts/stage4/acquire_national.py source
python scripts/stage4/national_graph.py source/israel-and-palestine-261008.osm.pbf national
python scripts/stage4/verify_national.py national
# ONLY disposable container, local socket, protected database name:
psql -X -h /var/run/postgresql -d trucksil_stage4_test_national -v ON_ERROR_STOP=1 < national/national-test.sql
```

Полный pipeline в .github/workflows/stage4-national.yml; contents:read,
без прав deploy/merge/записи репозитория. Предыдущий pipeline выполняется на PR.

## Полный проход исходника

4708889 сегментов; 4414569 узлов; 1112 компонент; 127464 конечных узлов; unknown oneway 3957312. 1662 несамопростых ways — кандидаты на аудит, не автоматически дефекты. 0 невалидных LineString ways. 1566 дополнительных повторов неориентированных пар ID — кандидаты наложений, не удалены.

Way37161098, пара8: одинаковый ID/координаты; геометрическое ребро не создано,
исходник не изменён. Relation12411556: to way914423926 отсутствует в PBF;
не восстановлен предположением. Все14463отношения остаются QUARANTINE.

Всего26188уникальных кандидатов:212nodes,11513ways,14463relations.
Категории пересекаются и не суммируются в число независимых ограничений:

| Категория | OSM-объекты |
|---|---:|
| maxheight | 881 |
| maxweight | 242 |
| maxaxleload | 0 |
| maxwidth | 41 |
| maxlength | 1 |
| hgv | 28 |
| hazmat | 0 |
| conditional | 355 |
| turn_restriction | 14737 |
| bridge_context | 5435 |
| tunnel_context | 5101 |

Bridge/tunnel context включает инфраструктуру вне highway и НЕ доказывает ограничение.
Отдельно highway ways:4902bridge,1891tunnel. VERIFIED0.

Полный парный аудит пересечений и геометрических дублей НЕ выполнен. Сравнение пяти
Shapely/PostGIS-предикатов на первых1000сегментах — детерминированная, нерепрезентативная
выборка. ST_Relate и ST_DWithin0.5м geography выполняются как отдельные диагностические
запросы, не объявляются независимой полной проверкой всей страны.

Производительность локального полного построения: 417.771с; peakRSS 2131292KiB. Это одна среда/один прогон, не SLA. В SQLite хранятся сырые теги и версии; source/provenance доступны через manifest и исходный PBF.


## Независимая локальная проверка завершена

NetworkX/Shapely проверены4708889строк и1112компонент;26188кандидатов прошли
Draft2020-12 research schema. 14407середин сегментов вне source polygon;
это наблюдение, не автоматическая ошибка complete-way экспорта.
Базовое сравнение JSON Schema:54случая,0расхождений (не полная conformance).
Полный отчёт: evidence/independent-checks.json.

Relations:320безfrom,324безto,117безvia;1345via-way,592с множественными
участниками ролей,2conditional,1missing source reference. Категории пересекаются;
ни одно отношение не выпущено из карантина. Значения разных transport-specific
restriction tags не объявлены правилами грузового движения.
Bridge highways безlayer429, tunnel highways безlayer475. Физические уровни UNKNOWN.
1079highway ways имеютarea=yes: сохранены контуры, НЕ проезжие оси/разрешения.
1112компонент/127464тупика/1662nonsimple ways/1566повторных пар ещё требуют
классификации: не все являются дефектами. Необычные layer (например1184) сохранены
сырыми; не нормализованы в физический уровень.

Исходные архивы120216068байт и412097524байт сохранены отдельно; SHA256 архивов
в manifest. Архив SQLite сформирован после завершения builder; независимые
отчёты сохраняются отдельно в Git/CI. Statement-level audit проверяется для
массовых операций, это не полноценная эксплуатационная история каждой строки.

Степень1 считается по числу инцидентных сегментов (параллельные сегменты сохранены). NetworkX независимо сверяет компоненты, но не доказывает причины каждого тупика/разрыва.


## Фактический GitHub Actions — PASS технических проверок

Полный национальный run38051002438 на6125b35272170a86e7950da4027c1b1e48a3eb2d:
-91/91unit tests(4.471s), включая19новых;72старых сохранены.
-54JSON Schema comparisons,0mismatches;26188кандидатов проверены Draft2020-12.
-4708889геометрий и4414569graph nodes;1112компонент NetworkX совпали.
-Полный результат воспроизведён против expected-summary.json; региональные длины
сверены с допуском1e-6км на агрегат, количества точные.
-PostgreSQL16.4/PostGIS3.4.3 в disposable container, network none, Unix socket.
-COPY533306ways,4414569nodes,4708889segments,26188candidates,14463relations.
-FK,source checksum reference,CHECK quarantine,geometry endpoints,GiST,
повторный полныйINSERT ON CONFLICT,statement audit,отклонение ошибочных
FK/source checksum/VERIFIED mutations и rollback всей схемы — PASS.
-Пространственный bbox-запрос использовал Bitmap Index Scan on segments_geom_gist:
2899строк,Execution Time1.556ms; это один запрос/один прогон, не SLA.
-Независимая проверка в CI227.030s; локально191.989s.
-Пять парных Shapely/PostGIS-предикатов совпали только в заявленной выборке1000.

Artifact11669364536 (719480969байт), срок до08.01.2027; бессрочность не обещается.
Source+SQLite отдельно сохранены в проектных архивах, указанных manifest.
Унаследованный pipeline38051006569 SUCCESS: stage2 migrations/checksums/audit/rollback,
пилот NetworkX/Shapely/PostGIS и91discovered unit tests (90OK,1skip только нового
osmium fixture, который фактически выполнен иPASS в национальном CI).

Эта приёмка относится к технической обработке источника. Подтверждённых официальных
грузовых ограничений0; маршруты не допущены к эксплуатации. Документальный
итоговый коммит не меняет проверенный код/источник; его SHA указан в PR3/отчёте.

Измеренное время COPY в CI: ways — 6,072 с; nodes — 8,469 с; segments — 92,722 с; candidates — 0,279 с; relations — 0,125 с. Время построения индексов и остальных проверок сюда не включено.

## Дополнение: производный автомобильный граф и полный индексированный аудит

Код следующей проверки: `35081efa8abdf4b8339821c6d6fef40a03b40c16`.
Предыдущий раздел с выборкой 1000 сегментов описывает первоначальную приёмку
исследовательского оригинала. Новый pipeline дополнительно перечисляет **все
пересекающиеся пары 533306 исходных highway ways** посредством STRtree/GiST:
948914 пар, сравнение IDs, DE-9IM и пяти предикатов. Это полный 2D-поиск по ways
имеющегося файла, а не измерение физических соединений или полноты реальных дорог.

Новые документы: AUTOMOTIVE_GRAPH_RU.md, BOUNDARY_AUDIT_RU.md,
GEOMETRY_ANOMALIES_RU.md, NATIONAL_INFRASTRUCTURE_RU.md,
TRUCK_RESTRICTION_CANDIDATES_RU.md и INDEPENDENT_AUDIT_RU.md.
Все большие реестры отделены от Git. Их исходный исследовательский граф сохранён.

Локально: 146/146 unittest; 54 JSON Schema comparisons/0 mismatches.
Полный независимый повтор проверил 533306 классификаций, 14407 внешних середин,
1534 группы повторных пар, 948914 пространственных пар, 14463 отношения и26188
кандидатов. Источники PBF/SQLite совпали по SHA до/после.
NetworkX автомобильного слоя:2363504узла,2488825уникальных неориентированных
рёбер при2488844сегментах,1365компонент. Разница19рёбер отражает параллельные
исходные сегменты, а не выполненное удаление данных.

SQL дополнительно проверяет автомобильное разбиение всех строк, исходные JSON
кандидатов, FK, запрет VERIFIED, геометрию границы, все отмеченные аномалии и все
индексированные пары. Запуск требует изолированной БД через Unix socket;
исходные и производные записи не применяются к эксплуатационной схеме.
Фактический итог PostGIS/CI фиксируется далее после завершения запуска.

## Итоговая фактическая приёмка — SUCCESS

Полный повтор на коде `f68209d5849c0a8c0c79a73be4986425cb9d3c4a`:
https://github.com/wf5ft6kh6d-debug/TrucksIL/actions/runs/38071577347.
Лог прочитан после завершения job114269884405; итог GitHub — success.

- 147/147 unit tests, без пропусков,5.316с; прежние91 сохранены.
- 54JSONSchema comparisons,0mismatches; ограниченный корпус, не full conformance.
- Полный PBF/SQLite/registry аудит, NetworkX и побайтовый повтор всех пяти
  SQLite/JSONL/SQL результатов — PASS.
- PostgreSQL16.4/PostGIS3.4.3: source+automotive+evidence full-row checks PASS.
- BOUNDARY PREDICATES PASS:14407случаев.
- GEOMETRY AUDIT PASS: все1662отмеченных ways и3100повторных сегментов.
- INFRASTRUCTURE FULL INDEXED PAIR COMPARISON PASS: весь набор948914пар,
  IDs,DE-9IM и пять предикатов совпали; это уже не первоначальная выборка1000.
- Четыре транзакции завершились ROLLBACK; защитные ограничения БД/Unix socket
  не ослаблены. Git fsck успешен.

Время стадий по GitHub: rebuild+verify522с; пять слоёв/независимый аудит/повтор714с;
PostGIS195с. Первые производители:44.66/12.48/30.44/143.09/6.73с соответственно
automotive/boundary/geometry/infrastructure/truck-evidence. Это один runner,
не SLA и не измерение предельной производительности.

CI artifact11678385127:1367891384байт, digest
`sha256:dc0b5ed77b6a9117da2aad297ccd4820daf253291e37348ef850177469b156c3`,
срок до2027-01-08T17:24:05Z. Архив для владельца с отдельно сохранёнными
производными данными описан в evidence/derived-artifacts.json.
Машинный итог: evidence/derived-ci-results.json.

Источник PBF сохранил исходный SHA. В CI rebuilt SQLite имела SHA
`b85473b3fa65030172579f19e8791a780dc558b6db3841a87ddc8daefc7472c1`
до и после; различие с локальным физическим SHA не подменяет полную сверку
исходных записей, которая также PASS.

Первый сбой35081ef сохранён в журнале и машинном отчёте. Он исправлен;
финальный отчёт не объявляет ошибочный запуск успешным. Итоговый документальный
коммит меняет только docs/stage4; проверенный код и входные данные совпадают
с f68209d. Все ограничения остаются QUARANTINE, VERIFIED=0.
