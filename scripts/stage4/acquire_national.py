"""Download pinned public source, verify exact content. No mutable latest URL."""
import json,sys,urllib.request,hashlib
from pathlib import Path
m=json.loads(Path('data/stage4/national-source-manifest.json').read_text());p=Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True);target=p/m['source_file']
if not target.exists():
 with urllib.request.urlopen(m['url'],timeout=120) as r, target.with_suffix('.partial').open('wb') as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   f.write(b)
 target.with_suffix('.partial').rename(target)
h=hashlib.sha256()
with target.open('rb') as f:
 for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
assert target.stat().st_size==m['size_bytes'] and h.hexdigest()==m['sha256'],'Pinned source mismatch; do not replace manifest automatically'
print('PINNED SOURCE SHA256 PASS',h.hexdigest())
