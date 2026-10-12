"""Conservative research-only conditional semantics; never permission evidence."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Jerusalem')
DAYS = ('Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su')

def parse_conditional(raw, source=None):
    out = {'raw': raw, 'source': source, 'status': 'QUARANTINE',
           'navigation_eligible': False, 'parse_status': 'UNKNOWN', 'reasons': []}
    if not isinstance(raw, str):
        out['reasons'] = ['non_string_rule']; return out
    match = re.fullmatch(r'\s*([a-z_]+|\d+(?:\.\d+)?)\s*@\s*\(([^()]*)\)\s*', raw)
    if not match:
        out['reasons'] = ['unsupported_expression']; return out
    value, condition = match.groups()
    match = re.fullmatch(r'(?:(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?\s+)?(\d\d:\d\d)-(\d\d:\d\d)', condition.strip())
    if not match:
        out['reasons'] = ['unsupported_days_times_holidays_or_multiple_clauses']; return out
    first, last, start, end = match.groups()
    def minute(text, endpoint=False):
        h, m = map(int, text.split(':'))
        if endpoint and h == 24 and m == 0: return 1440
        if h > 23 or m > 59: raise ValueError
        return h * 60 + m
    try:
        start, end = minute(start), minute(end, True)
        if start == end: raise ValueError
    except ValueError:
        out['reasons'] = ['invalid_or_ambiguous_interval']; return out
    days = list(range(7)) if first is None else [DAYS.index(first)]
    if last:
        days = [(DAYS.index(first) + n) % 7 for n in range((DAYS.index(last)-DAYS.index(first)) % 7 + 1)]
    out.update(parse_status='SUPPORTED', value=value, days=days, start_minute=start,
               end_minute=end, timezone='Asia/Jerusalem', interval='start_inclusive_end_exclusive')
    return out

def evaluate_conditional(record, instant):
    result = {'active': None, 'status': 'UNKNOWN', 'navigation_eligible': False, 'reasons': []}
    if record.get('parse_status') != 'SUPPORTED':
        result['reasons'] = ['unsupported_rule']; return result
    if not isinstance(instant, dt.datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        result['reasons'] = ['aware_instant_required']; return result
    local = instant.astimezone(ZONE)
    # Reject imaginary wall times supplied directly with ZoneInfo.
    if instant.tzinfo == ZONE and instant.astimezone(dt.timezone.utc).astimezone(ZONE).replace(tzinfo=None) != instant.replace(tzinfo=None):
        result['reasons'] = ['nonexistent_wall_time']; return result
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        result['reasons'] = ['ambiguous_wall_time']; return result
    minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60000000
    start, end, day = record['start_minute'], record['end_minute'], local.weekday()
    if end > start:
        active = day in record['days'] and start <= minute < end
    else:
        active = (day in record['days'] and minute >= start) or ((day-1) % 7 in record['days'] and minute < end)
    result.update(active=active, status='RESEARCH_EVALUATED', reasons=[])
    return result

def iter_temporal_records(db, source):
    """Yield each conditional tag once, retaining original object and field linkage."""
    import json
    seen = set()
    for table, object_type in (('ways', 'way'), ('relations', 'relation'), ('candidates', None)):
        query = 'SELECT id,tags' + (',type' if object_type is None else '') + ' FROM ' + table + ' ORDER BY id'
        for row in db.execute(query):
            obj_type = object_type or {'n':'node','w':'way','r':'relation'}.get(row[2], row[2])
            for key, value in sorted(json.loads(row[1]).items()):
                if ':conditional' not in key: continue
                identity = (obj_type, row[0], key)
                if identity in seen: continue
                seen.add(identity)
                record = parse_conditional(value, source)
                record.update(object_type=obj_type, object_id=row[0], tag_key=key)
                if not key.endswith(':conditional'):
                    record.update(parse_status='UNKNOWN', reasons=['unsupported_tag_qualifier'])
                yield record
