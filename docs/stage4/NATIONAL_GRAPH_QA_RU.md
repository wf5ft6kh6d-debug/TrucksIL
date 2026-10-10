# Национальный граф: техническая приёмка

Сохранены72прежних теста. Добавлены19тестов правил направлений, геометрии,
категорий, provenance и масштабирования DSU; синтетические случаи только в tests.
Локально91/91тестPASS с национальными зависимостями. Полный PostGIS CI до завершения имеет статус IN_PROGRESS.
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
