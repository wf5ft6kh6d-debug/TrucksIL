"""Independent Draft 2020-12 check of every generated pilot geometry (limited contract)."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from jsonschema import Draft202012Validator
from ingest_restrictions import SCHEMA, _schema


def check(path):
    data=json.loads(Path(path).read_text())
    schema=SCHEMA['properties']['geometry']
    Draft202012Validator.check_schema(schema)
    engine=Draft202012Validator(schema)
    count=0
    for feature in data['nodes']+data['segments']:
        geometry=feature['geometry']
        _schema(geometry,schema)
        engine.validate(geometry)
        count+=1
    assert count > 0
    print(f'{count} real pilot geometries accepted by local and independent Draft 2020-12 engines; no full conformance claim.')

if __name__=='__main__': check(sys.argv[1])
