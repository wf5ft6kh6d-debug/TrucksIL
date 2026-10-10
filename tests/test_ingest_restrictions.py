"""Synthetic contract tests. No record represents any real road or restriction."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AS_OF = '2026-10-09T08:00:00Z'


def synthetic_record():
    return {
        'id': 'SYNTHETIC-TEST-ONLY-001',
        'roadSegmentId': 'SYNTHETIC-NONEXISTENT-SEGMENT',
        'notes': 'SYNTHETIC TEST ONLY: no real road or legal claim',
        'restrictionType': 'max_height', 'value': 4.0, 'unit': 'm',
        'status': 'unverified', 'direction': 'unknown',
        'observedAt': '2026-10-01T00:00:00Z',
        'checkedAt': '2026-10-08T00:00:00Z',
        'reviewDueAt': '2026-10-20T00:00:00Z',
        'verifier': 'SYNTHETIC-TEST-ACTOR',
        'evidence': [{'reference': 'https://example.invalid/synthetic-evidence',
                      'retrievedAt': '2026-10-08T00:00:00Z',
                      'summary': 'Synthetic fixture, no actual evidence'}],
        'source': {'name': 'SYNTHETIC TEST SOURCE',
                   'reference': 'https://example.invalid/source',
                   'kind': 'other', 'authenticatedOfficial': False,
                   'license': {'identifier': 'SYNTHETIC-TEST-NOT-A-LICENCE',
                               'reference': 'https://example.invalid/license',
                               'decision': 'pending',
                               'checkedAt': '2026-10-08T00:00:00Z',
                               'reviewDueAt': '2026-10-20T00:00:00Z',
                               'reviewer': 'SYNTHETIC-TEST-ACTOR'}}}


def verified_fixture():
    r = synthetic_record()
    r.update(status='verified', direction='both', verifiedAt='2026-10-08T00:00:00Z')
    r['source']['license']['decision'] = 'permitted'
    r['independentReview'] = {'reviewer': 'SYNTHETIC-SECOND-ACTOR', 'reviewedAt': '2026-10-08T00:00:00Z', 'decision': 'approved', 'reference': 'https://example.invalid/review'}
    return r


class ImportContract(unittest.TestCase):
    def run_import(self, records, jsonl=False, raw=None, existing=None):
        with tempfile.TemporaryDirectory() as directory:
            inp, out = Path(directory) / ('input.jsonl' if jsonl else 'input.json'), Path(directory) / 'output.json'
            body = raw if raw is not None else ('\n'.join(json.dumps(r) for r in records) if jsonl else json.dumps(records))
            inp.write_text(body, encoding='utf-8')
            if existing is not None:
                out.write_text(existing, encoding='utf-8')
            p = subprocess.run([sys.executable, str(ROOT / 'src/ingest_restrictions.py'), str(inp), '--as-of', AS_OF, '--output', str(out)], capture_output=True, text=True)
            return p, out.read_text(encoding='utf-8') if out.exists() else None

    def assert_rejected(self, record):
        p, output = self.run_import([record])
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIsNone(output, 'Rejected records must not create output')

    def test_valid_unverified_json_and_jsonl(self):
        for jsonl in (False, True):
            with self.subTest(jsonl=jsonl):
                p, out = self.run_import([synthetic_record()], jsonl=jsonl)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIsNotNone(out)

    def test_verified_fixture_structurally_valid_only(self):
        p, _ = self.run_import([verified_fixture()])
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_required_provenance_fields(self):
        for key in ('source', 'observedAt', 'checkedAt', 'reviewDueAt', 'verifier', 'evidence'):
            with self.subTest(key=key):
                r = synthetic_record(); del r[key]; self.assert_rejected(r)

    def test_verified_gates(self):
        mutations = [lambda r: r.pop('independentReview'),
                     lambda r: r['independentReview'].update(reviewer=r['verifier']),
                     lambda r: r['independentReview'].update(decision='rejected'),
                     lambda r: r.pop('verifiedAt'),
                     lambda r: r.update(verifiedAt=None),
                     lambda r: r.update(direction='unknown'),
                     lambda r: r.update(reviewDueAt='2026-10-09T08:00:00Z'),
                     lambda r: r['source']['license'].update(decision='pending'),
                     lambda r: r['source']['license'].update(decision='denied'),
                     lambda r: r['source']['license'].update(reviewDueAt='2026-10-09T08:00:00Z'),
                     lambda r: r['source'].update(kind='user_report')]
        for idx, mutate in enumerate(mutations):
            with self.subTest(case=idx):
                r = verified_fixture(); mutate(r); self.assert_rejected(r)

    def test_official_user_separation(self):
        for kind, authenticated in [('official', False), ('user_report', True), ('other', True)]:
            with self.subTest(kind=kind):
                r = synthetic_record(); r['source'].update(kind=kind, authenticatedOfficial=authenticated); self.assert_rejected(r)

    def test_type_unit_and_value(self):
        for typ, val, unit in [('max_height', 4, 't'), ('max_gross_weight', 10, 'm'), ('max_axle_weight', 0, 't'), ('max_width', -1, 'm'), ('max_length', True, 'm'), ('truck_prohibited', 0, 'boolean'), ('hazmat_restriction', 1, 'boolean')]:
            with self.subTest(typ=typ, val=val):
                r = synthetic_record(); r.update(restrictionType=typ, value=val, unit=unit); self.assert_rejected(r)

    def test_location_missing_empty_or_invalid(self):
        for geometry in [None, {'type': 'Point', 'coordinates': [181, 0]}, {'type': 'Point', 'coordinates': [0, 91]}, {'type': 'Point', 'coordinates': [0]}, {'type': 'LineString', 'coordinates': [[0, 0]]}]:
            with self.subTest(geometry=geometry):
                r = synthetic_record(); r.pop('roadSegmentId')
                if geometry is not None: r['geometry'] = geometry
                self.assert_rejected(r)
        r = synthetic_record(); r['roadSegmentId'] = ''; self.assert_rejected(r)

    def test_timestamps(self):
        for key, date in [('checkedAt', 'not-a-date'), ('checkedAt', '2026-10-08T00:00:00+01:99'), ('checkedAt', '2026-10-08T00:00:00-00:99'), ('checkedAt', '2026-10-08T00:00:00-00:00'), ('observedAt', '2026-10-01'), ('observedAt', '2026-10-10T00:00:00Z'), ('checkedAt', '2026-10-10T00:00:00Z')]:
            with self.subTest(key=key, date=date):
                r = synthetic_record(); r[key] = date; self.assert_rejected(r)

    def test_nonfinite_json_is_rejected(self):
        for value in [float('nan'), float('inf'), float('-inf')]:
            with self.subTest(value=value):
                r = synthetic_record(); r['value'] = value; self.assert_rejected(r)

    def test_duplicates_are_rejected(self):
        p, out = self.run_import([synthetic_record(), synthetic_record()])
        self.assertNotEqual(p.returncode, 0); self.assertIsNone(out)

    def test_atomic_batch_rejection_preserves_existing_output(self):
        invalid = synthetic_record(); invalid['id'] = 'SYNTHETIC-BAD'; invalid['unit'] = 't'
        p, out = self.run_import([synthetic_record(), invalid], existing='PRESERVE EXISTING OUTPUT')
        self.assertNotEqual(p.returncode, 0); self.assertEqual(out, 'PRESERVE EXISTING OUTPUT')

    def test_unexpected_fields_rejected(self):
        r = synthetic_record(); r['safeForTrucks'] = True; self.assert_rejected(r)

    def test_unknown_coverage_never_certifies_route(self):
        for records in ([], [synthetic_record()], [verified_fixture()]):
            with self.subTest(count=len(records)):
                p, out = self.run_import(records)
                self.assertEqual(p.returncode, 0, p.stdout)
                result = json.loads(out)
                self.assertIs(result['routeSafetyCertified'], False)
                self.assertEqual(result['coverageStatus'], 'unknown')
                self.assertEqual(result['routeSuitability'], 'unknown')

    def test_duplicate_json_keys_rejected(self):
        p, out = self.run_import([], raw='[{"id":"first","id":"second"}]')
        self.assertNotEqual(p.returncode, 0); self.assertIsNone(out)

    def test_unsupported_schema_keywords_fail_closed(self):
        spec = importlib.util.spec_from_file_location('trucksil_importer_test', ROOT / 'src/ingest_restrictions.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for schema in ({'anyOf': [{'unsupportedAssertion': True}, {'type': 'number'}]}, {'if': {'unsupportedAssertion': True}, 'else': {'type': 'number'}}):
            with self.subTest(schema=schema):
                with self.assertRaises(ValueError):
                    module._schema(1, schema)

    def test_malformed_input_rejected(self):
        p, out = self.run_import([], raw='{broken')
        self.assertNotEqual(p.returncode, 0); self.assertIsNone(out)


if __name__ == '__main__':
    unittest.main()
