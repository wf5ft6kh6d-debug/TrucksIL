"""Run the five research producers, independent acceptance and exact replay.

The original national database is input only. Large output belongs outside Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def produce(source, output):
    commands = [
        ['automotive_graph.py', str(source), str(output/'automotive')],
        ['boundary_audit.py', '--database', str(source), '--boundary', 'data/stage4/source-boundary.poly', '--output', str(output/'boundary')],
        ['geometry_audit.py', str(source), str(output/'geometry'), '--automotive', str(output/'automotive/automotive.sqlite')],
        ['infrastructure_audit.py', str(source), str(output/'infrastructure'), '--sql-export', '--all-road-pairs'],
        ['truck_evidence.py', '--database', str(source), '--output', str(output/'truck-evidence')],
    ]
    timings = {}
    for name, *args in commands:
        start = time.monotonic()
        with (output/(name+'.log')).open('w') as log:
            subprocess.run([sys.executable, 'scripts/stage4/'+name, *args], stdout=log, stderr=subprocess.STDOUT, check=True)
        timings[name] = time.monotonic()-start
        print(name, 'completed', round(timings[name], 2), 'seconds', flush=True)
    return timings


def deterministic_files(folder):
    # Timings, local paths and process logs are intentionally excluded. The entire
    # derived SQLite and every JSONL registry / generated SQL are compared exactly.
    return {str(p.relative_to(folder)): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.suffix in ('.sqlite', '.jsonl', '.sql')}


def run(source, pbf, output, repeat=False):
    source, pbf, output = Path(source), Path(pbf), Path(output)
    if output.exists():
        raise ValueError('Refuse existing output directory')
    before = {'pbf': digest(pbf), 'sqlite': digest(source)}
    expected = json.loads(Path('data/stage4/national-source-manifest.json').read_text())['sha256']
    if before['pbf'] != expected:
        raise ValueError('Source PBF checksum mismatch')
    output.mkdir(parents=True)
    timings = produce(source, output)
    subprocess.run([sys.executable, 'scripts/stage4/independent_audit.py', '--source', str(source), '--pbf', str(pbf),
                    '--automotive', str(output/'automotive/automotive.sqlite'), '--audit-root', str(output),
                    '--output', str(output/'independent-audit.json')], check=True)
    files = deterministic_files(output)
    replay = {'status': 'NOT_RUN'}
    if repeat:
        repeated = output.with_name(output.name+'-repeat')
        if repeated.exists():
            raise ValueError('Refuse existing replay directory')
        repeated.mkdir()
        replay_timings = produce(source, repeated)
        repeated_files = deterministic_files(repeated)
        if files != repeated_files:
            raise ValueError('Repeat output differs: '+str([k for k in set(files)|set(repeated_files) if files.get(k)!=repeated_files.get(k)]))
        replay = {'status': 'PASS', 'entire_artifacts_compared': files, 'producer_seconds': replay_timings}
        shutil.rmtree(repeated)  # Only this invocation's freshly generated replay.
    after = {'pbf': digest(pbf), 'sqlite': digest(source)}
    if before != after:
        raise ValueError('Original input changed')
    report = {'source_before': before, 'source_after': after, 'originals_unchanged': True,
              'producer_seconds': timings, 'repeat': replay, 'files_sha256': files,
              'navigation_approved': False, 'verified_restrictions': 0}
    (output/'pipeline-manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source'); p.add_argument('pbf'); p.add_argument('output')
    p.add_argument('--repeat', action='store_true')
    a = p.parse_args(); run(a.source, a.pbf, a.output, a.repeat)
