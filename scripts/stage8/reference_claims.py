"""Private immutable reference inventory; never a legal-rule importer.

One row per substantive line (a review unit, not an atomic legal proposition).
Offsets are UTF-8 bytes and Unicode code points, exclusive at the end.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def inventory(raw):
    text = raw.decode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    section = 'preamble'
    byte_start = char_start = 0
    rows = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.strip()
        heading = re.match(r'^#{2,3} (\d+(?:\.\d+)?)\.', stripped)
        if heading:
            section = heading.group(1)
        owner = ('bridges' if section in {'1.3', '2', '2.1', '2.2', '2.3'}
                 else 'vehicle' if section in {'2.4', '4', '5'}
                 else 'coverage' if section == '8' else 'norms')
        structural = (not stripped or stripped.startswith('#') or stripped == '---'
                      or bool(re.fullmatch(r'[| :\-]+', stripped)))
        if not structural:
            rows.append({'id': f'REF-L{number:03}', 'section': section, 'owner': owner,
                         'line': number, 'span_chars': [char_start, char_start + len(line)],
                         'span_bytes': [byte_start, byte_start + len(line.encode('utf-8'))],
                         'text': line, 'text_sha256': hashlib.sha256(line.encode('utf-8')).hexdigest(),
                         'source_sha256': digest, 'evidence_status': 'QUARANTINE',
                         'interpretation_status': 'UNKNOWN', 'navigation_eligible': False,
                         'reason': 'User reference assertion; independent evidence review required.'})
        byte_start += len(line.encode('utf-8'))
        char_start += len(line)
    return {'schema_version': 'stage8.private-reference.v1', 'source_sha256': digest,
            'size_bytes': len(raw), 'line_count': len(text.splitlines()),
            'unit_definition': 'substantive source line; not independent road fact', 'records': rows}


def validate(raw, result):
    if result != inventory(raw):
        raise ValueError('Reference inventory differs from exact immutable bytes')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.reference.read_bytes()
    result = inventory(raw)
    validate(raw, result)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
