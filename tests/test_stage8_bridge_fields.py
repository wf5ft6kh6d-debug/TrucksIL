"""Synthetic fixtures only: field loss, false evidence and mutated lineage regressions."""
import copy
import unittest
from scripts.stage6.bridge_gaps import build_registry
from scripts.stage7.bridge_review import assess
from scripts.stage8.bridge_fields import append_fields
from tests.test_stage7_bridge_review import fixture


class BridgeFieldsTests(unittest.TestCase):
    def inputs(self):
        r = fixture()
        r.update(road_reference_raw='SYNTHETIC', chainage={'value':'1.234','unit':'km'},
                 future_field={'retain': ['SYNTHETIC']}, geometry=None, direction='UNKNOWN')
        g = build_registry([r])['records']
        return [r], g, assess([r],g)

    def test_all_historical_fields_retained_exactly(self):
        rows,g6,g7 = self.inputs()
        result=append_fields(rows,g6,g7)[0]
        self.assertEqual(result['historical_record'],rows[0])
        self.assertEqual(result['historical_record']['chainage']['unit'],'km')

    def test_independent_copy_no_input_mutation(self):
        args=self.inputs(); before=copy.deepcopy(args)
        result=append_fields(*args)
        result[0]['historical_record']['future_field']['retain'].append('changed')
        self.assertEqual(args,before)

    def test_no_inferred_units_mass_threshold_or_survey_order(self):
        r=append_fields(*self.inputs())[0]
        self.assertIsNone(r['mass_threshold_for_unknown_height'])
        self.assertEqual(r['measurement_needed'],'UNKNOWN_DOCUMENT_REVIEW_FIRST')
        self.assertEqual(r['external_row_check'],'NOT_RUN')
        self.assertFalse(r['navigation_eligible'])

    def test_prior_gap_tampering_rejected(self):
        args=self.inputs();args[2][0]['lane']='inferred'
        with self.assertRaises(ValueError): append_fields(*args)

    def test_duplicate_prior_review_rejected(self):
        args=self.inputs();args[2].append(copy.deepcopy(args[2][0]))
        with self.assertRaises(ValueError): append_fields(*args)

    def test_false_current_evidence_rejected(self):
        args=self.inputs();args[2][0]['current_evidence']=['unproven']
        with self.assertRaises(ValueError): append_fields(*args)

    def test_stable_repeat(self):
        args=self.inputs()
        self.assertEqual(append_fields(*args),append_fields(*args))
