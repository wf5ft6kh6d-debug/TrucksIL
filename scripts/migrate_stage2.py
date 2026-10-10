"""Prepare/apply checksummed v1 baseline + v2 candidate, disposable local DB only.

No upgrades of existing unversioned schemas. No automatic production connection.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[1]
FILES=['db/stage2.sql','db/migrations/0002_closed_ingest.sql']

def migration_sql(database):
    if not re.fullmatch(r'trucksil_stage2_test_[a-zA-Z0-9_]+',database):
        raise ValueError('requires disposable database name trucksil_stage2_test_*')
    bodies=[(ROOT/p).read_text() for p in FILES]
    digests=[hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in FILES]
    checks=' OR '.join(f"NOT EXISTS (SELECT 1 FROM trucksil_stage2.schema_migrations WHERE version={i+1} AND sha256='{h}')" for i,h in enumerate(digests))
    body=bodies[0].replace('BEGIN;\n','',1)
    if not body.rstrip().endswith('COMMIT;'): raise ValueError('unexpected baseline transaction boundary')
    body=body.rstrip()[:-len('COMMIT;')]
    return "\\set ON_ERROR_STOP on\nBEGIN;\n"+f"""
DO $$ BEGIN
 IF current_database() <> '{database}' OR inet_server_addr() IS NOT NULL THEN
  RAISE EXCEPTION 'Disposable local Unix-socket database required';
 END IF;
END $$;
SELECT pg_advisory_xact_lock(782194,2);
SELECT to_regnamespace('trucksil_stage2') IS NOT NULL AS already_installed \\gset
\\if :already_installed
DO $$ BEGIN
 IF to_regclass('trucksil_stage2.schema_migrations') IS NULL THEN
  RAISE EXCEPTION 'Existing unversioned schema: automatic upgrade refused';
 END IF;
 IF (SELECT count(*) FROM trucksil_stage2.schema_migrations) <> 2 OR {checks} THEN
  RAISE EXCEPTION 'Migration version/checksum mismatch: manual review required';
 END IF;
END $$;
\\else
"""+body+'\n'+bodies[1]+"""
CREATE TABLE trucksil_stage2.schema_migrations (
 version integer PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON trucksil_stage2.schema_migrations FROM PUBLIC;
"""+'\n'.join(f"INSERT INTO trucksil_stage2.schema_migrations(version,sha256) VALUES ({i+1},'{h}');" for i,h in enumerate(digests))+"\n\\endif\nCOMMIT;\n"

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True)
    p.add_argument('--socket',default='/var/run/postgresql')
    p.add_argument('--apply',action='store_true',help='explicit opt-in; default prints SQL only')
    a=p.parse_args()
    sql=migration_sql(a.database)
    if a.apply:
        if not a.socket.startswith('/'): p.error('socket must be an absolute local directory')
        subprocess.run(['psql','-X','--no-password','--host='+a.socket,'--dbname='+a.database,'--set=ON_ERROR_STOP=1'],input=sql,text=True,check=True)
    else: print(sql)
