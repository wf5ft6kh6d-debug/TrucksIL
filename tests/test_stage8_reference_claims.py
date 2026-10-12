"""SYNTHETIC reference fixtures; no user material in Git or CI."""
import copy
import unittest
from scripts.stage8.reference_claims import inventory, validate


class ReferenceInventoryTests(unittest.TestCase):
    def test_unicode_exact_offsets(self):
        raw = '# SYNTHETIC\n## 1. Test\nשלום — test\n'.encode()
        result = inventory(raw)
        row = result['records'][0]
        self.assertEqual(raw[slice(*row['span_bytes'])].decode(), row['text'])
        self.assertEqual(raw.decode()[slice(*row['span_chars'])], row['text'])
        self.assertTrue(validate(raw, result))

    def test_duplicate_text_has_distinct_source_positions(self):
        rows = inventory(b'SYNTHETIC\nSYNTHETIC\n')['records']
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])
        self.assertNotEqual(rows[0]['span_bytes'], rows[1]['span_bytes'])

    def test_owner_boundaries(self):
        text = '### 1.3. Test\nx\n### 2.4. Test\nx\n## 8. Test\nx\n## 9. Test\nx\n'
        self.assertEqual([x['owner'] for x in inventory(text.encode())['records']],
                         ['bridges', 'vehicle', 'coverage', 'norms'])

    def test_no_status_escalation(self):
        raw = b'SYNTHETIC verified assertion\n'
        result = inventory(raw)
        result['records'][0]['evidence_status'] = 'VERIFIED'
        with self.assertRaises(ValueError):
            validate(raw, result)

    def test_content_mutation_rejected(self):
        with self.assertRaises(ValueError):
            validate(b'SYNTHETIC changed', inventory(b'SYNTHETIC original'))

    def test_crlf_and_final_line_preserved(self):
        raw = b'SYNTHETIC\r\nfinal'
        result = inventory(raw)
        self.assertEqual(''.join(x['text'] for x in result['records']).encode(), raw)

    def test_invalid_utf8_rejected(self):
        with self.assertRaises(UnicodeDecodeError):
            inventory(b'\xff')

    def test_structural_lines_not_claims(self):
        self.assertEqual(inventory(b'# SYNTHETIC\n\n---\n|---|---|\n')['records'], [])
