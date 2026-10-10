"""JSON semantics regressions; no road data."""
import copy
import importlib.util
from pathlib import Path
import unittest
from test_ingest_restrictions import synthetic_record, AS_OF

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('validator', ROOT / 'src/ingest_restrictions.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

class SchemaRegressions(unittest.TestCase):
    def test_enum_and_const_distinguish_boolean_recursively(self):
        for left, right in [(True, 1), (False, 0), ([True], [1]),
                            ({'x': True}, {'x': 1}), ({'x': [False]}, {'x': [0]})]:
            for a, b in [(left, right), (right, left)]:
                for schema in [{'enum': [b]}, {'const': b}]:
                    with self.subTest(value=a, schema=schema):
                        with self.assertRaises(ValueError): v._schema(a, schema)

    def test_json_equal_positive_and_negative_cases(self):
        for a, b in [(1, 1.0), (None, None), (True, True),
                     ({'a': [1, False], 'b': None}, {'b': None, 'a': [1.0, False]})]:
            v._schema(a, {'const': b}); v._schema(a, {'enum': [b]})
        for a, b in [(None, False), ('1', 1), ([1], [1, 2]), ({'x': 1}, {'y': 1})]:
            with self.assertRaises(ValueError): v._schema(a, {'const': b})

    def test_minlength_counts_original_string(self):
        for value in [' ', '\t', '\n', 'א', '😀']:
            v._schema(value, {'type': 'string', 'minLength': 1})
        v._schema(' a ', {'minLength': 3})
        with self.assertRaises(ValueError): v._schema('', {'minLength': 1})
        with self.assertRaises(ValueError): v._schema('😀', {'minLength': 2})

    def test_nonblank_is_explicit_record_policy(self):
        for key in ['id', 'roadSegmentId', 'verifier', 'notes']:
            for text in ['', ' ', '\t\n']:
                r = synthetic_record(); r[key] = text
                with self.subTest(key=key, text=text):
                    with self.assertRaises(ValueError): v.validate_record(r, AS_OF)
        for path in [('source','name'), ('source','license','reviewer')]:
            r=synthetic_record(); target=r
            for key in path[:-1]: target=target[key]
            target[path[-1]]=' '
            with self.assertRaises(ValueError): v.validate_record(r, AS_OF)
        r=synthetic_record(); r['id']=' padded-id '; v.validate_record(r, AS_OF)
        self.assertEqual(r['id'], ' padded-id ')

    def test_unknown_keywords_in_inactive_branches(self):
        for schema in [{'if': {'const': 0}, 'then': {'not': {}}},
                       {'if': {}, 'else': {'not': {}}},
                       {'properties': {'unused': {'format': 'email'}}}]:
            with self.assertRaises(ValueError): v._schema(1, schema)

if __name__ == '__main__': unittest.main()
