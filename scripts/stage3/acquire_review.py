"""One bounded current-version comparison; does not replace the frozen pilot."""
import argparse,gzip,hashlib,json,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from acquire_members import LICENSE,BBOX,ENDPOINT
IDS=[10115408,10115411,12303230,13395546]
QUERY='[out:json][timeout:45][maxsize:1048576];rel(id:'+','.join(map(str,IDS))+');(._;>>;);out meta;'

def main(output):
 p=Path(output)
 if p.exists():raise ValueError('Refuse overwrite')
 url=ENDPOINT+'?'+urllib.parse.urlencode({'data':QUERY})
 req=urllib.request.Request(url,headers={'User-Agent':'TrucksIL-Research/0.1 (https://github.com/wf5ft6kh6d-debug/TrucksIL)','Accept-Encoding':'identity'})
 with urllib.request.urlopen(req,timeout=70) as r:
  if r.status!=200 or r.url!=url:raise ValueError('Unexpected response/redirect')
  raw=r.read(1048577);headers={k:r.headers.get(k) for k in ('Content-Type','Date','ETag','Last-Modified')}
 if len(raw)>1048576:raise ValueError('Response too large')
 d=json.loads(raw)
 if 'remark' in d or {e['id'] for e in d['elements'] if e['type']=='relation'}!=set(IDS):raise ValueError('Partial/missing relations')
 m={'query':QUERY,'source_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_snapshot_at':d['osm3s']['timestamp_osm_base'],'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'license':LICENSE,'bbox_wgs84':BBOX,'scope':'four relation version comparisons only; never merge into pilot','http_headers':headers}
 p.mkdir(parents=True);(p/'raw.json.gz').write_bytes(gzip.compress(raw,mtime=0));(p/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'bytes':len(raw),'sha256':m['sha256'],'elements':len(d['elements'])}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--output',required=True);main(a.parse_args().output)
