"""One explicit small read-only Overpass acquisition; never retries or bypasses errors."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

BBOX = [34.990, 32.811, 35.004, 32.821]  # west,south,east,north; research window only
QUERY = '''[out:json][timeout:45][maxsize:16777216];
way["highway"](32.811,34.990,32.821,35.004)->.roads;
(.roads;node(w.roads);rel(bw.roads)["type"="restriction"];);
out meta;
'''
ENDPOINT = 'https://overpass-api.de/api/interpreter'
LICENSE = {'identifier': 'ODbL-1.0', 'decision': 'permitted',
           'reference': 'https://opendatacommons.org/licenses/odbl/1-0/',
           'evidence_url': 'https://www.openstreetmap.org/copyright',
           'checked_on': '2026-10-10', 'reviewer': 'TrucksIL source review',
           'scope': 'OSM pilot and its separate derived database only',
           'attribution': '© OpenStreetMap contributors',
           'obligations': ['attribution', 'ODbL share-alike and access to derived database',
                           'no government endorsement; no navigation certification']}

def acquire(destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite an acquisition')
    url = ENDPOINT + '?' + urllib.parse.urlencode({'data': QUERY})
    request = urllib.request.Request(url, headers={
        'User-Agent': 'TrucksIL-Research/0.1 (https://github.com/wf5ft6kh6d-debug/TrucksIL)',
        'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(request, timeout=70) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Response too large')
        if response.status != 200 or response.url != url:
            raise ValueError('Unexpected status/redirect; manual review required')
        headers = {k: response.headers.get(k) for k in ('Content-Type','Date','Last-Modified','ETag')}
    payload = json.loads(raw)
    if 'remark' in payload or not payload.get('elements'):
        raise ValueError('Overpass partial/error/empty result; not an accepted snapshot')
    timestamp = payload['osm3s']['timestamp_osm_base']
    manifest = {'dataset_id': 'osm-haifa-lower-city-pilot', 'source_url': url,
                'endpoint': ENDPOINT, 'query': QUERY, 'bbox_wgs84': BBOX,
                'retrieved_at': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                'http_headers': headers, 'source_snapshot_at': timestamp,
                'publication_date': None, 'format': 'Overpass JSON', 'crs': 'EPSG:4326',
                'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                'raw_file': 'raw.json', 'license': LICENSE,
                'owner': 'OpenStreetMap contributors; database licensed by OSM Foundation',
                'distributor': 'Overpass API', 'authenticated_official': False,
                'route_safety_certified': False, 'coverage_status': 'unknown',
                'notes': ['OSM edit timestamps are not field observation dates',
                          'Whole ways can extend outside requested bbox',
                          'Related restriction relations may have members outside this snapshot']}
    destination.mkdir(parents=True)
    (destination/'raw.json').write_bytes(raw)
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'sha256':manifest['sha256'],'bytes':len(raw),
                      'elements':len(payload['elements']), 'source_snapshot_at':timestamp}))

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    acquire(p.parse_args().output)
