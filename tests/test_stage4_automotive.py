"""Regression cases are synthetic fixtures, not real travel permissions."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.stage4.automotive_graph import classify, build, sha256


class AutomotivePolicyTests(unittest.TestCase):
    def test_missing_access_is_not_permission(self):
        d=classify({'highway':'primary'})
        self.assertEqual(d['status'],'INCLUDED');self.assertEqual(d['access_status'],'UNKNOWN');self.assertEqual(d['truck_access'],'UNKNOWN')

    def test_area_not_centerline(self):
        self.assertEqual(classify({'highway':'residential','area':'yes','motorcar':'yes'})['status'],'EXCLUDED')

    def test_nonmotor_classes(self):
        for c in ('footway','pedestrian','cycleway','steps','bridleway','corridor','platform'):
            self.assertEqual(classify({'highway':c})['status'],'EXCLUDED')

    def test_footway_permission_requires_review(self):
        self.assertEqual(classify({'highway':'footway','motor_vehicle':'yes'})['status'],'QUARANTINE')

    def test_unknown_classes_quarantined(self):
        for c in ('track','path','road','escape','raceway','unknown'):
            self.assertEqual(classify({'highway':c})['status'],'QUARANTINE')

    def test_lifecycle(self):
        self.assertEqual(classify({'highway':'construction'})['status'],'EXCLUDED')
        self.assertEqual(classify({'highway':'primary','disused:highway':'primary'})['status'],'QUARANTINE')

    def test_explicit_access_precedence(self):
        d=classify({'highway':'primary','access':'no','vehicle':'no','motor_vehicle':'no','motorcar':'yes'})
        self.assertEqual(d['status'],'INCLUDED');self.assertEqual(d['access_key'],'motorcar');self.assertEqual(d['truck_access'],'UNKNOWN')
        self.assertEqual(classify({'highway':'primary','access':'yes','motor_vehicle':'no'})['status'],'EXCLUDED')

    def test_limited_permissions_not_general_access(self):
        for v in ('destination','delivery','customers','agricultural','permit','yes;no','unknown',''):
            self.assertEqual(classify({'highway':'service','access':v})['status'],'QUARANTINE')

    def test_private_access_excluded(self):
        self.assertEqual(classify({'highway':'service','access':'private'})['status'],'EXCLUDED')

    def test_conditional_scoped_access(self):
        for key in ('motor_vehicle:conditional','access:conditional','vehicle:forward','motorcar:backward'):
            self.assertEqual(classify({'highway':'primary',key:'no'})['status'],'QUARANTINE')

    def test_hgv_does_not_grant_or_remove_car_access(self):
        for value in ('yes','no','delivery'):
            d=classify({'highway':'primary','hgv':value,'hgv:conditional':'no @ (Mo-Fr)'})
            self.assertEqual(d['status'],'INCLUDED');self.assertEqual(d['truck_access'],'UNKNOWN');self.assertEqual(d['hgv_tags']['hgv'],value);self.assertFalse(d['independently_verified'])

    def test_direction_variants_quarantined(self):
        for tags in ({'oneway':'reversible'},{'oneway':'alternating'},{'oneway:conditional':'no @ (Su)'}):
            self.assertEqual(classify({'highway':'primary',**tags})['status'],'QUARANTINE')

    def test_blanket_access_designated_has_no_defined_mode(self):
        d=classify({'highway':'primary','access':'designated'})
        self.assertEqual(d['status'],'QUARANTINE');self.assertEqual(d['access_status'],'UNKNOWN')

    def test_unrecognized_area(self):
        self.assertEqual(classify({'highway':'primary','area':'maybe'})['status'],'QUARANTINE')

    def test_reproducible_build_partition_and_source_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.sqlite'
            con=sqlite3.connect(source)
            con.executescript('CREATE TABLE ways(id INTEGER PRIMARY KEY,version INTEGER,timestamp TEXT,tags TEXT,nodes TEXT);CREATE TABLE nodes(id INTEGER PRIMARY KEY,lon REAL,lat REAL);CREATE TABLE segments(id INTEGER PRIMARY KEY,way_id INTEGER,seq INTEGER,a INTEGER,b INTEGER,direction TEXT,geom TEXT,length_m REAL,tile TEXT);')
            for i,h in enumerate(('primary','footway','track'),1):
                con.execute('INSERT INTO ways VALUES(?,?,?,?,?)',(i,1,'2026-10-08',json.dumps({'highway':h}),'[1,2]'))
                con.execute('INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?)',(i,i,0,1,2,'unknown','LINESTRING(35 32,35.001 32)',94.,'35,32'))
            con.executemany('INSERT INTO nodes VALUES(?,?,?)',[(1,35.,32.),(2,35.001,32.)]);con.commit();con.close()
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'license':'ODbL-1.0','attribution':'© OpenStreetMap contributors','sha256':'a'*64,'snapshot_at':'2026-10-08T20:21:06Z'}))
            before=sha256(source)
            with contextlib.redirect_stdout(io.StringIO()):
                a=build(source,root/'one',manifest);b=build(source,root/'two',manifest)
            self.assertEqual(sha256(source),before)
            self.assertEqual(a['segment_counts'],{'EXCLUDED':1,'INCLUDED':1,'QUARANTINE':1})
            self.assertEqual(a['automotive_nodes'],2);self.assertEqual(a['automotive_directions'],{'unknown':1})
            self.assertEqual(a['output_sqlite_sha256'],b['output_sqlite_sha256'])
            self.assertFalse(a['navigation_approved'])
            with self.assertRaises(ValueError):build(source,root/'one',manifest)
