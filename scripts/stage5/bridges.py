"""Read-only, dependency-free OOXML intake. Outputs are PRIVATE until licensed.

No road matching, unit inference, verification or navigational clearance is done.
"""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HEADERS = {
    'A': 'שם הגשר', 'B': 'כביש', 'C': 'ק"מ התחלה',
    'D': '04.18 מרווח אנכי חופשי מינימלי קיים מתחת לגשר בתחום תנועה',
    'E': '04.19 מרווח אנכי חופשי',
    'F': '04.21 ערך שילוט מגבלת גובה קיים בפועל',
    'G': '04.23 גובה נציב מכסימלי',
}
DIMENSIONS = {'D': 'minimum_vertical_clearance', 'E': 'free_vertical_clearance',
              'F': 'posted_height_limit', 'G': 'pier_height'}


def decimal_value(raw, *, allow_zero=False):
    """Parse numeric syntax only; no unit, current validity or precision inference."""
    if not isinstance(raw, str) or len(raw) > 80 or not re.fullmatch(r'[+]?(?:\d+(?:\.\d*)?|\.\d+)', raw):
        return None
    try:
        value = Decimal(raw)
        if value < 0 or (not allow_zero and value == 0):
            return None
        return format(value, 'f')
    except InvalidOperation:
        return None


def _text(element):
    return ''.join(n.text or '' for n in element.findall('.//s:t', NS))


def read_workbook(path):
    """Retain source cell references/types/formulas, never evaluate cached formula values."""
    content = Path(path).read_bytes()
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 100_000_000:
            raise ValueError('workbook uncompressed size exceeds intake limit')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [_text(e) for e in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', NS)]
        rels = {r.get('Id'): r for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        metadata = {}
        if 'docProps/core.xml' in archive.namelist():
            # Contributor identities are not needed for source validity.
            for e in ET.fromstring(archive.read('docProps/core.xml')):
                key = e.tag.rsplit('}', 1)[-1]
                if key in ('created', 'modified'):
                    metadata[key] = e.text
        sheets = []
        for sheet in workbook.findall('s:sheets/s:sheet', NS):
            rel = rels[sheet.get('{'+REL+'}id')]
            if rel.get('TargetMode') == 'External':
                raise ValueError('external sheet unsupported')
            target = rel.get('Target', '')
            member = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not member.startswith('xl/worksheets/'):
                raise ValueError('unexpected sheet relationship target')
            xml = ET.fromstring(archive.read(member))
            rows = []
            for row in xml.findall('s:sheetData/s:row', NS):
                cells = {}
                for cell in row.findall('s:c', NS):
                    address = cell.get('r', '')
                    if not re.fullmatch(r'[A-Z]+[1-9]\d*', address) or int(re.sub('[A-Z]', '', address)) != int(row.get('r')):
                        raise ValueError('invalid cell/row reference')
                    if address in cells:
                        raise ValueError('duplicate cell address')
                    value = cell.find('s:v', NS)
                    raw = value.text if value is not None and value.text is not None else None
                    kind = cell.get('t', 'n')
                    if kind == 's' and raw is not None:
                        raw = strings[int(raw)]
                    elif kind == 'inlineStr':
                        raw = _text(cell)
                    formula = cell.find('s:f', NS)
                    cells[address] = {'raw': raw, 'type': kind, 'formula': None if formula is None else (formula.text or ''), 'style': cell.get('s')}
                rows.append({'row': int(row.get('r')), 'cells': cells})
            if len({r['row'] for r in rows}) != len(rows):
                raise ValueError('duplicate row number')
            sheets.append({'name': sheet.get('name'), 'member': member, 'rows': rows})
    return {'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content),
            'internal_metadata_dates': metadata, 'sheets': sheets}


def normalize_workbook(path, *, retrieved_at=None):
    book = read_workbook(path)
    records = []
    sheet_summary = []
    populated = Counter()
    for sheet in book['sheets']:
        nonempty = [r for r in sheet['rows'] if any(c['raw'] is not None or c['formula'] is not None for c in r['cells'].values())]
        if not nonempty:
            sheet_summary.append({'name': sheet['name'], 'data_rows': 0, 'layout': 'EMPTY'})
            continue
        header = nonempty[0]
        actual = {re.sub(r'\d', '', k): v['raw'] for k, v in header['cells'].items()}
        recognized = actual == HEADERS and all(c['formula'] is None for c in header['cells'].values())
        # Unknown layouts preserve every row, including a possible header.
        data = nonempty[1:] if recognized else nonempty
        sheet_summary.append({'name': sheet['name'], 'data_rows': len(data), 'layout': 'RECOGNIZED' if recognized else 'UNKNOWN'})
        for row in data:
            index = row['row']
            def cell(column):
                return row['cells'].get(f'{column}{index}', {'raw': None, 'type': 'n', 'formula': None})
            dimensions = {}
            for col, meaning in DIMENSIONS.items():
                c = cell(col)
                numeric = decimal_value(c['raw']) if recognized and c['type'] in ('n', 's', 'inlineStr') and c['formula'] is None else None
                dimensions[meaning] = {'raw': c['raw'], 'parsed_decimal': numeric, 'unit': 'UNKNOWN', 'interpretation': 'UNKNOWN'}
                if c['raw'] is not None and recognized:
                    populated[meaning] += 1
            reasons = ['NO_CONFIRMED_LICENSE', 'ORIGIN_UNVERIFIED', 'CURRENT_VALIDITY_UNKNOWN',
                       'HEIGHT_UNITS_UNKNOWN', 'ROAD_AND_DIRECTION_UNMATCHED']
            if not recognized:
                reasons.append('UNSUPPORTED_LAYOUT')
            if any(c['formula'] is not None for c in row['cells'].values()):
                reasons.append('FORMULA_NOT_EVALUATED')
            records.append({
                'record_id': f"xlsx:{book['sha256']}:{sheet['member']}:{index}",
                'source': {'sha256': book['sha256'], 'sheet': sheet['name'], 'member': sheet['member'], 'row': index, 'cells': row['cells']},
                'status': 'QUARANTINE', 'interpretation': 'UNKNOWN', 'navigation_eligible': False,
                'dimensions': dimensions, 'road_reference_raw': cell('B')['raw'] if recognized else None,
                'chainage': {'raw': cell('C')['raw'], 'value': decimal_value(cell('C')['raw'], allow_zero=True) if recognized and cell('C')['formula'] is None and cell('C')['type'] in ('n', 's', 'inlineStr') else None, 'unit': 'km' if recognized else 'UNKNOWN'},
                'geometry': None, 'direction': 'UNKNOWN', 'reasons': reasons,
            })
    manifest = {k: book[k] for k in ('sha256', 'size_bytes', 'internal_metadata_dates')}
    manifest.update({'source_kind': 'USER_PROVIDED_XLSX', 'retrieved_at': retrieved_at,
                     'license': 'UNKNOWN', 'publisher': 'UNKNOWN', 'measurement_date': 'UNKNOWN',
                     'filename_date_is_not_measurement_date': True, 'redistribution_allowed': False,
                     'sheets': sheet_summary})
    return {'manifest': manifest, 'records': records, 'summary': {
        'record_count': len(records), 'status_counts': {'QUARANTINE': len(records), 'VERIFIED': 0, 'UNKNOWN': 0},
        'interpretation_counts': {'UNKNOWN': len(records)}, 'populated_dimensions': dict(populated),
        'matched_roads': 0, 'navigation_eligible': 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--retrieved-at')
    args = parser.parse_args()
    result = normalize_workbook(args.input, retrieved_at=args.retrieved_at)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in ('manifest', 'summary'):
        (args.output_dir / f'{name}.json').write_text(json.dumps(result[name], ensure_ascii=False, sort_keys=True, indent=2)+'\n')
    (args.output_dir/'records.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in result['records']))
    print(json.dumps(result['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
