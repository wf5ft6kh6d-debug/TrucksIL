"""Optional independent Draft 2020-12 comparison; exit 2 when unavailable."""
import copy
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / p) for p in ('src','tests')]
try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    print('NOT RUN: jsonschema is not installed'); sys.exit(2)
import ingest_restrictions as local
from test_ingest_restrictions import synthetic_record, verified_fixture
Draft202012Validator.check_schema(local.SCHEMA)
cases=[]
for record in [synthetic_record(), verified_fixture()]:
    cases.append((record,local.SCHEMA))
    for key in local.SCHEMA['required']:
        changed=copy.deepcopy(record); del changed[key]; cases.append((changed,local.SCHEMA))
    for value in [-1,0,1,True,'1']:
        changed=copy.deepcopy(record); changed['value']=value; cases.append((changed,local.SCHEMA))
    for value in ['', ' ', ' padded ']:
        changed=copy.deepcopy(record); changed['id']=value; cases.append((changed,local.SCHEMA))
for a,b in [(True,1),([True],[1]),({'x':True},{'x':1}),(1,1.0),(None,None)]:
    cases.extend([(a,{'enum':[b]}),(a,{'const':b})])
cases.extend([(s,{'type':'string','minLength':1}) for s in ['', ' ', '\n', '😀']])
failures=0
for value,schema in cases:
    expected=Draft202012Validator(schema,format_checker=FormatChecker()).is_valid(value)
    try: local._schema(value,schema); actual=True
    except ValueError: actual=False
    if actual!=expected: failures+=1; print('MISMATCH',repr(value),schema)
print(f'{len(cases)} comparisons; {failures} mismatches. Limited corpus, not full conformance.')
sys.exit(bool(failures))
