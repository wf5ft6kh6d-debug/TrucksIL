"""Adversarial checks for the independent auditor, not producer rule mirrors."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('stage4_independent',Path(__file__).resolve().parents[1]/'scripts/stage4/independent_audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class IndependentAuditTests(unittest.TestCase):
    def test_readonly_cannot_modify_original(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'source.sqlite'
            db=sqlite3.connect(path);db.execute('CREATE TABLE test(id INTEGER)');db.commit();db.close()
            before=audit.digest(path);db=audit.readonly(path)
            with self.assertRaises(sqlite3.OperationalError):db.execute('INSERT INTO test VALUES(1)')
            db.close();self.assertEqual(before,audit.digest(path))

    def test_nonempty_wal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'source.sqlite';path.touch();Path(str(path)+'-wal').write_bytes(b'uncheckpointed')
            with self.assertRaisesRegex(ValueError,'WAL'):audit.readonly(path)

    def test_direction_mutation_detected_without_trusting_summary(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.sqlite';derived=Path(td)/'derived.sqlite'
            for path,direction in [(source,'unknown'),(derived,'both')]:
                db=sqlite3.connect(path)
                db.executescript('CREATE TABLE ways(id INTEGER); INSERT INTO ways VALUES(1); CREATE TABLE nodes(id INTEGER); INSERT INTO nodes VALUES(1); CREATE TABLE segments(id INTEGER,direction TEXT);')
                db.execute('INSERT INTO segments VALUES(1,?)',(direction,));db.commit();db.close()
            with self.assertRaises(AssertionError):audit.automotive_reconcile(source,derived)

if __name__=='__main__':unittest.main()
