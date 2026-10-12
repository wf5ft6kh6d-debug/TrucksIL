"""Separate proof, interpretation, currency, geobinding and publication decisions."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from scripts.stage7.contract import canonical, sha256, validate_source

SCHEMA = json.loads((Path(__file__).resolve().parents[2]/'data/stage8/review.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

def validate_review(row, sources=None, public=False):
    VALIDATOR.validate(row)
    if sources is not None and not set(row['sources']).issubset(sources):
        raise ValueError('Unregistered evidence source')
    if public and row['rights_status'] != 'PUBLIC_METADATA_ONLY':
        raise ValueError('Public output requires explicit publication review')
    # CURRENT/BOUND describes an independently reviewed dimension, not road VERIFIED.
    canonical(row)
    return row
