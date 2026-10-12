"""All records are SYNTHETIC; no private workbook or road identifiers in CI."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.stage6.bridge_gaps import DIMENSIONS, REQUIRED, build_gap, build_registry, process_accepted


def synthetic(row=2, present=('minimum_vertical_clearance',)):
    source = {'sha256': 'a'*64, 'sheet': 'SYNTHETIC', 'member': 'xl/worksheets/sheet1.xml', 'row': row}
    return {'record_id': f"xlsx:{source['sha256']}:{source['member']}:{row}", 'source': source,
            'status': 'QUARANTINE', 'navigation_eligible': False,
            'dimensions': {key: {'raw': 'SYNTHETIC 5' if key in present else None,
                                 'parsed_decimal': '5' if key in present else None,
                                 'unit': 'UNKNOWN'} for key in DIMENSIONS}}


class BridgeGapTests(unittest.TestCase):
    def test_all_gates_remain_open(self):
        r = build_gap(synthetic())
        gates = {g['gate']: g for g in r['evidence_gaps']}
        self.assertTrue(set(REQUIRED) <= gates.keys())
        self.assertTrue(all(g['status'] == 'UNKNOWN' and g['evidence'] == [] for g in gates.values()))

    def test_no_current_checks_invented(self):
        r = build_registry([synthetic()])
        self.assertEqual(r['summary']['externally_checked_rows'], 0)
        self.assertEqual(r['records'][0]['external_row_check']['status'], 'NOT_RUN')
        self.assertFalse(r['records'][0]['navigation_eligible'])

    def test_priority_is_review_order_not_safety(self):
        cases = [(('posted_height_limit', 'minimum_vertical_clearance'), 1),
                 (('posted_height_limit',), 2), (('free_vertical_clearance',), 3),
                 (('pier_height',), 4), ((), 5)]
        for present, rank in cases:
            r = build_gap(synthetic(present=present))
            self.assertEqual(r['priority'], rank)
            self.assertFalse(r['priority_is_risk_score'])

    def test_pier_does_not_fill_clearance(self):
        r = build_gap(synthetic(present=('pier_height',)))
        self.assertIn('PHYSICAL_CLEARANCE_VALUE_MISSING', [g['gate'] for g in r['evidence_gaps']])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            build_registry([synthetic(), synthetic()])

    def test_promoted_inputs_rejected(self):
        for field, value in [('status', 'VERIFIED'), ('navigation_eligible', True), ('navigation_eligible', 0)]:
            r = synthetic(); r[field] = value
            with self.assertRaises(ValueError): build_gap(r)

    def test_unknown_dimensions_fail_closed(self):
        r = synthetic(); r['dimensions']['structure_height'] = {}
        with self.assertRaises(ValueError): build_gap(r)

    def test_unparsed_value_not_treated_as_missing(self):
        r = synthetic(); r['dimensions']['minimum_vertical_clearance']['parsed_decimal'] = None
        gap = build_gap(r)
        self.assertIn('UNPARSED_MEASUREMENT', [g['gate'] for g in gap['evidence_gaps']])
        self.assertTrue(gap['dimension_presence']['minimum_vertical_clearance'])

    def test_stable_order_no_input_mutation(self):
        rows = [synthetic(4), synthetic(2)]
        original = deepcopy(rows)
        self.assertEqual(build_registry(rows), build_registry(list(reversed(rows))))
        self.assertEqual(rows, original)
        self.assertEqual(build_registry(rows)['records'][0]['source']['row'], 2)

    def test_private_processor_validates_provenance_and_repeats(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            rows = base/'records.jsonl'; manifest = base/'manifest.json'; summary = base/'summary.json'
            rows.write_text(json.dumps(synthetic())+'\n')
            manifest.write_text(json.dumps({'sha256':'a'*64}))
            summary.write_text(json.dumps({'record_count':1}))
            process_accepted(rows, manifest, summary, base/'out')
            before = (base/'out/bridge-evidence-gaps.jsonl').read_bytes()
            process_accepted(rows, manifest, summary, base/'out')
            self.assertEqual(before, (base/'out/bridge-evidence-gaps.jsonl').read_bytes())
            with self.assertRaises(ValueError): process_accepted(rows, manifest, summary, base)
            manifest.write_text(json.dumps({'sha256':'b'*64}))
            with self.assertRaises(ValueError): process_accepted(rows, manifest, summary, base/'out')

    def test_count_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base/'records.jsonl').write_text(json.dumps(synthetic())+'\n')
            (base/'manifest.json').write_text(json.dumps({'sha256':'a'*64}))
            (base/'summary.json').write_text(json.dumps({'record_count':2}))
            with self.assertRaises(ValueError):
                process_accepted(base/'records.jsonl', base/'manifest.json', base/'summary.json', base/'out')


if __name__ == '__main__': unittest.main()
