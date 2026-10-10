#!/usr/bin/env python3
"""Validate a local restriction batch. Never fetch, deploy, or certify a route."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'data/restrictions.schema.json').read_text())


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('timestamp must be RFC3339 with timezone')
    if not value.endswith('Z'):
        offset = value[-6:]
        if int(offset[1:3]) > 23 or int(offset[4:6]) > 59 or offset == '-00:00':
            raise ValueError('timestamp requires a valid known timezone offset')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timestamp timezone required')
    return result


SUPPORTED_KEYWORDS = {'$schema','title','description','type','required','properties','additionalProperties','enum','const','minimum','maximum','exclusiveMinimum','minLength','minItems','maxItems','prefixItems','items','format','pattern','allOf','anyOf','oneOf','if','then','else'}


def _check_schema(spec):
    """Inspect all branches before evaluating data; schema errors cannot be mismatches."""
    if not isinstance(spec, dict) or set(spec) - SUPPORTED_KEYWORDS:
        raise ValueError('unsupported schema keywords or schema form')
    if 'format' in spec and spec['format'] != 'date-time':
        raise ValueError('unsupported schema format')
    if 'additionalProperties' in spec and not isinstance(spec['additionalProperties'], bool):
        raise ValueError('unsupported additionalProperties schema')
    types = spec.get('type', [])
    types = [types] if isinstance(types, str) else types
    if not isinstance(types, list) or any(t not in ('object','array','string','number','boolean','null') for t in types):
        raise ValueError('unsupported schema type')
    for child in spec.get('properties', {}).values():
        _check_schema(child)
    for key in ('items','if','then','else'):
        if key in spec:
            _check_schema(spec[key])
    for key in ('prefixItems','allOf','anyOf','oneOf'):
        for child in spec.get(key, []):
            _check_schema(child)


def _schema(value, spec, path='$'):
    _check_schema(spec)
    return _validate_schema(value, spec, path)


def json_equal(left, right):
    """JSON equality: numbers compare mathematically; booleans are distinct."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is bool and type(right) is bool and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    return left == right


def _validate_schema(value, spec, path='$'):
    """Small validator for ONLY the keywords used in the checked-in schema.

    Unknown assertion keywords fail closed to prevent silently weakening future edits.
    """
    supported = {'$schema','title','description','type','required','properties','additionalProperties','enum','const','minimum','maximum','exclusiveMinimum','minLength','minItems','maxItems','prefixItems','items','format','pattern','allOf','anyOf','oneOf','if','then','else'}
    if set(spec) - supported:
        raise ValueError(f'{path}: unsupported schema keywords {set(spec) - supported}')
    def fail(message):
        raise ValueError(f'{path}: {message}')
    types = spec.get('type')
    if types:
        types = [types] if isinstance(types, str) else types
        matches = {'object': isinstance(value, dict), 'array': isinstance(value, list), 'string': isinstance(value, str), 'number': isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value), 'boolean': isinstance(value,bool), 'null': value is None}
        if not any(matches.get(t, False) for t in types):
            fail(f'expected {types}')
    if 'enum' in spec and not any(json_equal(value, candidate) for candidate in spec['enum']):
        fail('not an allowed enum value')
    if 'const' in spec and not json_equal(value, spec['const']):
        fail('unexpected constant')
    if isinstance(value, dict):
        for key in spec.get('required', []):
            if key not in value:
                fail(f'missing {key}')
        if spec.get('additionalProperties') is False and set(value) - set(spec.get('properties',{})):
            fail('unknown properties')
        for key, child in spec.get('properties',{}).items():
            if key in value:
                _validate_schema(value[key], child, f'{path}.{key}')
    if isinstance(value, list):
        if len(value) < spec.get('minItems',0) or len(value) > spec.get('maxItems',math.inf):
            fail('array length out of range')
        for i, child in enumerate(spec.get('prefixItems',[])):
            if i < len(value):
                _validate_schema(value[i],child,f'{path}[{i}]')
        for i, item in enumerate(value):
            if 'items' in spec and i >= len(spec.get('prefixItems',[])):
                _validate_schema(item,spec['items'],f'{path}[{i}]')
    if isinstance(value, str):
        if len(value) < spec.get('minLength',0):
            fail('empty string')
        if 'pattern' in spec and not re.search(spec['pattern'],value):
            fail('invalid pattern')
        if spec.get('format') == 'date-time':
            timestamp(value)
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if not math.isfinite(value):
            fail('nonfinite number')
        if value < spec.get('minimum',-math.inf) or value > spec.get('maximum',math.inf) or value <= spec.get('exclusiveMinimum',-math.inf):
            fail('number out of range')
    for child in spec.get('allOf',[]):
        _validate_schema(value,child,path)
    for key in ['anyOf','oneOf']:
        if key in spec:
            passes=0
            for child in spec[key]:
                try:
                    _validate_schema(value,child,path)
                    passes += 1
                except ValueError:
                    pass
            if passes == 0 or (key == 'oneOf' and passes != 1):
                fail(f'{key} failed')
    if 'if' in spec:
        try:
            _validate_schema(value,spec['if'],path)
            branch='then'
        except ValueError:
            branch='else'
        if branch in spec:
            _validate_schema(value,spec[branch],path)


def validate_record(record, as_of=None):
    """Structural and temporal acceptance only; evidence truth needs human review."""
    now = as_of or datetime.now(timezone.utc)
    if isinstance(now,str):
        now=timestamp(now)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('as_of must have timezone')
    _schema(record, SCHEMA)
    observed=timestamp(record['observedAt'])
    checked=timestamp(record['checkedAt'])
    due=timestamp(record['reviewDueAt'])
    if observed > checked or checked > now:
        raise ValueError('observation/check chronology invalid or future')
    license=record['source']['license']
    lc=timestamp(license['checkedAt']); ld=timestamp(license['reviewDueAt'])
    if lc > now or ld <= lc:
        raise ValueError('license review chronology invalid')
    for evidence in record['evidence']:
        if timestamp(evidence['retrievedAt']) > checked:
            raise ValueError('evidence retrieved after check')
    verified=record.get('verifiedAt')
    if verified is not None and not observed <= timestamp(verified) <= checked:
        raise ValueError('verification chronology invalid')
    if record['status'] == 'verified':
        review=record['independentReview']
        if review['reviewer'].strip().casefold() == record['verifier'].strip().casefold():
            raise ValueError('independent reviewer must differ from verifier')
        if not timestamp(verified) <= timestamp(review['reviewedAt']) <= checked:
            raise ValueError('independent review chronology invalid')
        if not checked < due or due <= now or ld <= now:
            raise ValueError('verified evidence or license overdue')
    elif record['status'] != 'expired' and due <= checked:
        raise ValueError('reviewDueAt must follow checkedAt')
    if record['status'] == 'expired' and due > now:
        raise ValueError('expired record has future review deadline')
    start=timestamp(record['effectiveFrom']) if 'effectiveFrom' in record else None
    end=timestamp(record['effectiveTo']) if 'effectiveTo' in record else None
    if start and end and end <= start:
        raise ValueError('effective date interval invalid')
    if record['status'] == 'verified' and end and end <= now:
        raise ValueError('verified restriction validity has expired')
    return record


def _no_constant(value):
    raise ValueError(f'nonstandard JSON number: {value}')


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key]=value
    return result


def read_batch(path):
    raw=Path(path).read_text(encoding='utf-8')
    kwargs={'parse_constant':_no_constant,'object_pairs_hook':_unique_object}
    if Path(path).suffix.lower() == '.jsonl':
        batch=[json.loads(line,**kwargs) for line in raw.splitlines() if line.strip()]
    else:
        batch=json.loads(raw,**kwargs)
    if not isinstance(batch,list):
        raise ValueError('input must be JSON array or .jsonl records')
    return batch


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--as-of',help='RFC3339 validation clock for reproducible tests; default current UTC')
    parser.add_argument('--output',type=Path,help='Optional local validated staging JSON; no database writes')
    args=parser.parse_args(argv)
    try:
        now=timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        batch=read_batch(args.input)
        ids=set()
        for index,record in enumerate(batch):
            try:
                validate_record(record,now)
                if record['id'] in ids:
                    raise ValueError('duplicate restriction id')
                ids.add(record['id'])
            except ValueError as exc:
                raise ValueError(f'record {index}: {exc}') from exc
        result={'validationAsOf':now.isoformat(),'recordCount':len(batch),'routeSafetyCertified':False,'routeSuitability':'unknown','coverageStatus':'unknown','records':batch}
        if args.output:
            if args.output.resolve() == args.input.resolve():
                raise ValueError('output must not overwrite input')
            # Replace atomically only after the WHOLE batch passes.
            name=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=args.output.parent,delete=False) as handle:
                    name=handle.name
                    json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
                    handle.write('\n')
                    handle.flush(); os.fsync(handle.fileno())
                os.replace(name,args.output)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
        print(json.dumps({k:v for k,v in result.items() if k != 'records'}))
        return 0
    except (ValueError,OSError,TypeError,OverflowError,RecursionError) as exc:
        print(json.dumps({'accepted':False,'error':str(exc),'routeSafetyCertified':False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
