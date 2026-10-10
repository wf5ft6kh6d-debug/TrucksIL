# Национальный граф: техническая приёмка

Сохранены72прежних теста. Добавлены15тестов правил направлений, геометрии,
категорий, provenance и масштабирования DSU; синтетические случаи только в tests.
Независимый национальный прогон и PostGIS до завершения имеют статус IN_PROGRESS.
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
