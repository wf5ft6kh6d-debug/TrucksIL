"""Offline runner guard tests. These do not execute PostgreSQL or prove SQL validity."""
import importlib.util
from pathlib import Path
import unittest
p=Path(__file__).resolve().parents[1]/'scripts/migrate_stage2.py'
s=importlib.util.spec_from_file_location('migrations',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class MigrationGuard(unittest.TestCase):
    def test_non_disposable_names_rejected(self):
        for name in ['production','trucksil','trucksil_stage2_test_',"trucksil_stage2_test_x';DROP DATABASE x;--",'trucksil_stage2_test_x\n']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):m.migration_sql(name)
    def test_plan_is_deterministic(self):
        self.assertEqual(m.migration_sql('trucksil_stage2_test_local'),m.migration_sql('trucksil_stage2_test_local'))
