import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator, ValidationError
from scripts.stage4.truck_evidence import build_record, parse_measurement

ROOT = Path(__file__).resolve().parents[1]

class TruckEvidenceTests(unittest.TestCase):
    def record(self, tags=None, cats=None):
        manifest=json.loads((ROOT/'data/stage4/national-source-manifest.json').read_text())
        return build_record(('way',1,2,'2026-10-08T00:00:00Z',json.dumps(tags or {'bridge':'yes'}),json.dumps(cats or ['bridge_context']),'{"type":"LineString","coordinates":[[34,32],[35,32]]}','QUARANTINE'),manifest)

    def test_implicit_units_are_not_assumed(self):
        self.assertIsNone(parse_measurement('maxheight','4.5')['value'])

    def test_explicit_dimensions_and_mass(self):
        self.assertEqual(parse_measurement('maxheight','4.5 m')['value'],4.5)
        self.assertEqual(parse_measurement('maxweight','3500 kg')['unit'],'kg')
        self.assertEqual(parse_measurement('maxweight','3.5 t')['value'],3.5)

    def test_ambiguous_illegal_values_preserved(self):
        for text in ['none','default','4;5','4.5 @ (Mo-Fr)','-1 m','0 m','NaN m','4 ft','4,5 m','9'*400+' m']:
            r=parse_measurement('maxheight',text)
            self.assertEqual(r['raw'],text)
            self.assertEqual(r['status'],'UNKNOWN')
        self.assertEqual(parse_measurement('maxheight','5 t')['status'],'UNKNOWN')

    def test_context_is_not_a_restriction(self):
        r=self.record()
        self.assertTrue(r['context_only'])
        self.assertEqual(r['truck_applicability'],'UNKNOWN')
        self.assertFalse(r['navigation_eligible'])

    def test_direction_and_condition_preserved_not_resolved(self):
        tags={'maxheight:forward':'4 m','hgv:conditional':'no @ (Mo-Fr 08:00-18:00)','oneway':'yes'}
        r=self.record(tags,['maxheight','conditional'])
        self.assertEqual(r['raw_tags'],tags)
        self.assertEqual(r['direction']['raw_tags']['oneway'],'yes')
        self.assertEqual(r['temporal_applicability']['raw_tags']['hgv:conditional'],tags['hgv:conditional'])
        self.assertEqual(r['direction']['status'],'UNKNOWN')

    def test_verification_cannot_be_promoted(self):
        schema=json.loads((ROOT/'data/stage4/truck-evidence.schema.json').read_text())
        v=Draft202012Validator(schema);r=self.record();v.validate(r)
        r['status']='VERIFIED'
        with self.assertRaises(ValidationError):v.validate(r)
        r=self.record();r['navigation_eligible']=True
        with self.assertRaises(ValidationError):v.validate(r)

    def test_exact_evidence_gates_and_quarantine_reason_required(self):
        schema=json.loads((ROOT/'data/stage4/truck-evidence.schema.json').read_text())
        v=Draft202012Validator(schema)
        r=self.record();r['acceptance']['required_gates']=['invented_'+str(i) for i in range(7)]
        with self.assertRaises(ValidationError):v.validate(r)
        r=self.record();r['acceptance']['gate_status']={'invented_'+str(i):'UNKNOWN' for i in range(7)}
        with self.assertRaises(ValidationError):v.validate(r)
        r=self.record();del r['quarantine_reason']
        with self.assertRaises(ValidationError):v.validate(r)
        r=self.record();del r['required_additional_evidence']
        with self.assertRaises(ValidationError):v.validate(r)

    def test_byte_exact_payload_and_provenance(self):
        r=self.record()
        self.assertEqual(json.loads(r['source_payload']['tags_json']),r['raw_tags'])
        self.assertEqual(r['provenance']['license'],'ODbL-1.0')
        self.assertEqual(r['osm']['version'],2)
        self.assertEqual(len(r['acceptance']['required_gates']),7)

if __name__ == '__main__': unittest.main()
