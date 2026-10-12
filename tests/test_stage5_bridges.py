"""All workbook fixtures are SYNTHETIC, not Israeli road measurements."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
import zipfile
from scripts.stage5.bridges import HEADERS, decimal_value, normalize_workbook, read_workbook


def synthetic_book(path, *, header=True, formula=False, extra_sheet=False, boolean=False):
    def text_cell(address, value):
        return f'<c r="{address}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    row1 = ''.join(text_cell(k+'1', v) for k, v in HEADERS.items()) if header else text_cell('A1', 'SYNTHETIC UNKNOWN LAYOUT')
    data = text_cell('A2', 'SYNTHETIC bridge')+text_cell('B2', 'SYNTHETIC road')+'<c r="C2"><v>0</v></c>'
    data += f'<c r="D2"'+(' t="b"' if boolean else '')+'>'+('<f>1+4</f>' if formula else '')+'<v>5</v></c>'
    data += '<c r="G2"><v>12</v></c>'
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="SYNTHETIC" r:id="r1"/>'+('<sheet name="EMPTY" r:id="r2"/>' if extra_sheet else '')+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData><row r="1">{row1}</row><row r="2">{data}</row></sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet2.xml', f'<worksheet xmlns="{ns}"><sheetData/></worksheet>')
        z.writestr('docProps/core.xml', '<p><created>2017-09-14T07:18:10Z</created><modified>2017-09-14T07:27:01Z</modified><creator>PRIVATE PERSON</creator></p>')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'SYNTHETIC.xlsx'

    def result(self, **kwargs):
        synthetic_book(self.path, **kwargs)
        return normalize_workbook(self.path)

    def test_original_preserved_and_sha_exact(self):
        synthetic_book(self.path)
        original = self.path.read_bytes()
        r = normalize_workbook(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(r['manifest']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(r['manifest']['size_bytes'], len(original))

    def test_row_cell_linkage(self):
        r = self.result()['records'][0]
        self.assertEqual(r['source']['row'], 2)
        self.assertEqual(r['source']['cells']['D2']['raw'], '5')
        self.assertTrue(r['record_id'].endswith(':xl/worksheets/sheet1.xml:2'))

    def test_no_units_or_matching_inferred(self):
        r = self.result()['records'][0]
        self.assertEqual(r['dimensions']['minimum_vertical_clearance']['unit'], 'UNKNOWN')
        self.assertEqual(r['chainage']['unit'], 'km')
        self.assertEqual(r['chainage']['value'], '0')
        self.assertEqual(r['direction'], 'UNKNOWN')
        self.assertIsNone(r['geometry'])

    def test_pier_height_never_used_as_clearance(self):
        r = self.result()['records'][0]
        self.assertEqual(r['dimensions']['pier_height']['parsed_decimal'], '12')
        self.assertEqual(r['dimensions']['minimum_vertical_clearance']['parsed_decimal'], '5')
        self.assertIsNone(r['dimensions']['posted_height_limit']['parsed_decimal'])

    def test_metadata_not_measurement_date(self):
        m = self.result()['manifest']
        self.assertEqual(m['internal_metadata_dates']['created'], '2017-09-14T07:18:10Z')
        self.assertNotIn('creator', m['internal_metadata_dates'])
        self.assertEqual(m['measurement_date'], 'UNKNOWN')
        self.assertFalse(m['redistribution_allowed'])

    def test_formula_not_used_as_value(self):
        r = self.result(formula=True)['records'][0]
        self.assertEqual(r['dimensions']['minimum_vertical_clearance']['raw'], '5')
        self.assertIsNone(r['dimensions']['minimum_vertical_clearance']['parsed_decimal'])
        self.assertIn('FORMULA_NOT_EVALUATED', r['reasons'])

    def test_boolean_not_used_as_measurement(self):
        r = self.result(boolean=True)['records'][0]
        self.assertIsNone(r['dimensions']['minimum_vertical_clearance']['parsed_decimal'])

    def test_unknown_layout_is_preserved_not_mapped(self):
        result = self.result(header=False)
        self.assertEqual(len(result['records']), 2)
        for r in result['records']:
            self.assertIn('UNSUPPORTED_LAYOUT', r['reasons'])
            self.assertIsNone(r['dimensions']['minimum_vertical_clearance']['parsed_decimal'])

    def test_empty_sheets_counted(self):
        r = self.result(extra_sheet=True)
        self.assertEqual(len(r['manifest']['sheets']), 2)
        self.assertEqual(r['manifest']['sheets'][1]['data_rows'], 0)

    def test_never_verified(self):
        r = self.result()
        self.assertEqual(r['summary']['status_counts']['VERIFIED'], 0)
        for row in r['records']:
            self.assertFalse(row['navigation_eligible'])
            self.assertEqual(row['status'], 'QUARANTINE')

    def test_numeric_syntax_is_not_rounded(self):
        self.assertEqual(decimal_value('4.3499999999999996'), '4.3499999999999996')
        for raw in ('0', '-1', 'NaN', 'Infinity', '4,5', '4 m', '4;5', None, '9'*81):
            self.assertIsNone(decimal_value(raw))

    def test_repeat_deterministic(self):
        synthetic_book(self.path)
        self.assertEqual(normalize_workbook(self.path), normalize_workbook(self.path))


if __name__ == '__main__':
    unittest.main()
